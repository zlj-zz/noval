import os
import threading
import logging
from typing import Dict, List, Tuple, Optional

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ProgressBar,
    Static,
)

from .config import config
from .downloader import Downloader
from .utils import slice_list


class SearchScreen(Screen):
    """搜索页面：输入小说名 -> 展示结果表格 -> 选择 -> 进入章节页"""

    search_results: reactive[List[Tuple[str, str]]] = reactive([])

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="search-screen"):
            yield Static("🔍 搜索小说", id="search-header")
            with Horizontal(id="search-bar"):
                yield Input(
                    placeholder="请输入小说名称...",
                    id="search-input",
                )
                yield Button("搜索", id="search-btn", variant="primary")
            yield DataTable(id="search-table")
            with Horizontal(id="search-actions"):
                yield Button("查看章节", id="view-chapters-btn", disabled=True)
                yield Button("返回主菜单", id="back-btn")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#search-table", DataTable)
        table.add_columns("书名", "作者/信息", "来源链接")
        table.cursor_type = "row"
        table.disabled = True
        self.query_one("#search-input", Input).focus()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "search-btn":
            await self.do_search()
        elif btn_id == "view-chapters-btn":
            self.go_to_chapters()
        elif btn_id == "back-btn":
            self.app.switch_screen("main")

    async def do_search(self) -> None:
        input_widget = self.query_one("#search-input", Input)
        name = input_widget.value.strip()
        if not name:
            self.notify("请输入小说名称", severity="warning")
            return

        self.notify(f"正在搜索 '{name}'...")
        table = self.query_one("#search-table", DataTable)
        table.clear()
        table.disabled = True

        def _search() -> List[Tuple[str, str]]:
            from .searcher import get_searcher

            return get_searcher("duckduckgo").search(name)

        results = await self.run_worker(_search, thread=True).wait()
        self.search_results = results

    def watch_search_results(self, results: List[Tuple[str, str]]) -> None:
        table = self.query_one("#search-table", DataTable)
        table.clear()
        if not results:
            self.notify("未找到搜索结果", severity="error")
            table.disabled = True
            self.query_one("#view-chapters-btn", Button).disabled = True
            return

        for text, url in results:
            parts = text.split("|")
            name = parts[0] if parts else "Unknown"
            info = parts[1] if len(parts) > 1 else ""
            table.add_row(name, info, url)

        table.disabled = False
        self.query_one("#view-chapters-btn", Button).disabled = False
        self.notify(f"找到 {len(results)} 条结果")

    def go_to_chapters(self) -> None:
        table = self.query_one("#search-table", DataTable)
        if table.cursor_row is None:
            self.notify("请先选择一本小说", severity="warning")
            return
        row_key = table.cursor_row
        if row_key is None or row_key >= len(self.search_results):
            return
        _, url = self.search_results[row_key]
        name = self.search_results[row_key][0].split("|")[0]
        self.app.push_screen(ChapterScreen(name, url))


class ChapterScreen(Screen):
    """章节页面：展示章节列表，选择范围，开始下载"""

    chapters: reactive[List[Tuple[str, str]]] = reactive([])

    def __init__(self, fiction_name: str, url: str) -> None:
        self.fiction_name = fiction_name
        self.url = url
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="chapter-screen"):
            yield Static(f"📚 {self.fiction_name}", id="chapter-title")
            yield Static("正在获取章节列表...", id="chapter-status")
            yield DataTable(id="chapter-table")
            with Horizontal(id="chapter-actions"):
                yield Button("下载全部", id="download-all-btn", disabled=True)
                yield Button("指定范围下载", id="download-range-btn", disabled=True)
                yield Button("返回", id="back-btn")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#chapter-table", DataTable)
        table.add_columns("章节名", "链接")
        table.cursor_type = "row"
        table.disabled = True
        self.run_worker(self._load_chapters, thread=True)

    async def _load_chapters(self) -> None:
        dl = Downloader(verify=False)
        chs = dl.get_chapters(self.url)
        self.app.call_from_thread(self._set_chapters, chs)

    def _set_chapters(self, chs: List[Tuple[str, str]]) -> None:
        self.chapters = chs
        self._on_chapters_loaded()

    def _on_chapters_loaded(self) -> None:
        table = self.query_one("#chapter-table", DataTable)
        status = self.query_one("#chapter-status", Static)
        if not self.chapters:
            status.update(
                "[red]未获取到章节列表[/red]\n该链接可能不是小说目录页，请返回搜索并选择其他结果。"
            )
            return
        status.update(f"共 {len(self.chapters)} 章")
        for title, url in self.chapters:
            table.add_row(title, url)
        table.disabled = False
        self.query_one("#download-all-btn", Button).disabled = False
        self.query_one("#download-range-btn", Button).disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "download-all-btn":
            self.start_download(self.chapters)
        elif btn_id == "download-range-btn":
            self.prompt_range()
        elif btn_id == "back-btn":
            self.app.pop_screen()

    def prompt_range(self) -> None:
        total = len(self.chapters)
        self.app.push_screen(
            RangeInputScreen(total),
            callback=self._on_range_selected,
        )

    def _on_range_selected(self, range_tuple: Optional[Tuple[int, int]]) -> None:
        if range_tuple is None:
            return
        start, end = range_tuple
        selected = self.chapters[start - 1 : end]
        self.start_download(selected)

    def start_download(self, chapters: List[Tuple[str, str]]) -> None:
        if not chapters:
            self.notify("没有可下载的章节", severity="warning")
            return
        self.app.push_screen(DownloadScreen(self.fiction_name, self.url, chapters))


class RangeInputScreen(Screen):
    """弹窗：输入章节范围"""

    def __init__(self, total: int) -> None:
        self.total = total
        super().__init__()

    def compose(self) -> ComposeResult:
        with Container(id="range-dialog"):
            yield Static(f"共 {self.total} 章，请输入下载范围")
            with Horizontal():
                yield Input(placeholder="起始章节", id="start-input")
                yield Static(" ~ ")
                yield Input(placeholder="结束章节", id="end-input")
            with Horizontal():
                yield Button("确认", id="confirm-btn", variant="primary")
                yield Button("取消", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
            return

        start_val = self.query_one("#start-input", Input).value.strip()
        end_val = self.query_one("#end-input", Input).value.strip()
        try:
            start = int(start_val)
            end = int(end_val)
            if not (1 <= start <= end <= self.total):
                self.notify(
                    f"范围无效，请输入 1-{self.total} 之间的数字", severity="error"
                )
                return
            self.dismiss((start, end))
        except ValueError:
            self.notify("请输入有效的数字", severity="error")


class DownloadScreen(Screen):
    """下载页面：进度条 + 日志输出"""

    def __init__(
        self,
        fiction_name: str,
        url: str,
        chapters: List[Tuple[str, str]],
    ) -> None:
        self.fiction_name = fiction_name
        self.url = url
        self.chapters = chapters
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="download-screen"):
            with Container(id="download-card"):
                yield Static(f"📥 正在下载", id="download-title")
                yield Static(f"《{self.fiction_name}》", id="download-subtitle")
                yield ProgressBar(total=len(self.chapters), id="download-progress")
                yield Static("准备下载...", id="download-status")
                yield Static("", id="download-log")
                yield Button("返回", id="back-btn")
        yield Footer()

    def on_mount(self) -> None:
        # 用原生 threading.Thread 启动下载，完全绕过 Textual worker 生命周期管理
        self._thread = threading.Thread(target=self._do_download, daemon=True)
        self._thread.start()

    def _do_download(self) -> None:
        """后台下载线程：捕获 app 引用，避免 screen pop 后 self.app 失效."""
        logger = logging.getLogger("noval.tui")
        logger.setLevel(logging.DEBUG)
        if not logger.handlers:
            fh = logging.FileHandler("/tmp/noval_download.log", mode="a")
            fh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            logger.addHandler(fh)

        # 提前捕获 app 引用，screen 被 pop 后 self.app 会抛 NoActiveAppError
        app = self.app
        fiction_name = self.fiction_name
        chapters = self.chapters
        url = self.url

        dl = Downloader(verify=False)
        save_dir = config.save_dir
        os.makedirs(save_dir, exist_ok=True)
        file_path = os.path.join(save_dir, f"{fiction_name}.txt")

        dl.clear(file_path)
        logger.debug(f"[DL] start {fiction_name} chapters={len(chapters)}")

        # 直接在后台线程更新 app 状态（dict 操作是 GIL 保护的，线程安全）
        app.active_downloads[fiction_name] = {
            "total": len(chapters),
            "current": 0,
            "status": "downloading",
        }

        def _ui_update(widget_id: str, method: str, *args) -> None:
            """通过 call_from_thread 在主线程执行 UI 更新，失败静默忽略."""

            def _do():
                try:
                    widget = self.query_one(widget_id)
                    getattr(widget, method)(*args)
                except Exception:
                    pass

            try:
                app.call_from_thread(_do)
            except Exception:
                pass

        try:
            for idx, (chapter_name, url) in enumerate(chapters):
                logger.debug(f"[DL] chapter {idx+1}/{len(chapters)} {chapter_name}")
                app.active_downloads[fiction_name]["current"] = idx + 1

                _ui_update("#download-status", "update", f"下载中: {chapter_name}")
                _ui_update(
                    "#download-log",
                    "update",
                    f"[{idx + 1}/{len(chapters)}] {chapter_name}",
                )
                _ui_update("#download-progress", "advance", 1)

                while True:
                    html, _ = dl.get_html(url)
                    if html:
                        break
                    _ui_update(
                        "#download-status", "update", f"跳过失败章节: {chapter_name}"
                    )
                    break

                if html:
                    content = dl._extractor.extract_content(html)
                    logger.debug(
                        f"[DL] chapter {idx+1} html_len={len(html)} content_len={len(content) if content else 0}"
                    )
                    if content:
                        chapter_text = f"{chapter_name}\n\n{content}\n\n"
                        dl.write(file_path, chapter_text, mode="a")
                else:
                    logger.debug(f"[DL] chapter {idx+1} no html")

            logger.debug(f"[DL] finished {fiction_name}")
            _ui_update("#download-status", "update", "下载完成!")
            app.active_downloads.pop(fiction_name, None)
            config.add_history(fiction_name, file_path, url)
            try:
                app.call_from_thread(
                    app.notify,
                    f"《{fiction_name}》下载完成，已保存到 {file_path}",
                )
            except Exception:
                pass
        except Exception as exc:
            logger.debug(f"[DL] exception {type(exc).__name__}: {exc}")
            app.active_downloads.pop(fiction_name, None)
            try:
                app.call_from_thread(
                    app.notify,
                    f"《{fiction_name}》下载出错: {exc}",
                    severity="error",
                )
            except Exception:
                pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()


class HistoryScreen(Screen):
    """历史记录页面"""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="history-screen"):
            yield Static("📚 下载历史", id="history-title")
            yield DataTable(id="history-table")
            with Horizontal():
                yield Button("重新下载", id="redownload-btn", disabled=True)
                yield Button("删除选中", id="delete-btn", disabled=True)
                yield Button("返回", id="back-btn")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#history-table", DataTable)
        table.add_columns("书名", "保存路径", "下载时间")
        table.cursor_type = "row"
        self._refresh_table()

    def _refresh_table(self) -> None:
        table = self.query_one("#history-table", DataTable)
        table.clear()
        if not config.history:
            table.add_row("暂无历史记录", "", "")
            table.disabled = True
            return
        for item in config.history:
            table.add_row(
                item.get("name", ""),
                item.get("path", ""),
                item.get("date", ""),
            )
        table.disabled = False
        self.query_one("#redownload-btn", Button).disabled = False
        self.query_one("#delete-btn", Button).disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "back-btn":
            self.app.switch_screen("main")
        elif btn_id == "delete-btn":
            table = self.query_one("#history-table", DataTable)
            row = table.cursor_row
            if row is not None and 0 <= row < len(config.history):
                del config.history[row]
                config.save()
                self._refresh_table()
                self.notify("已删除")
        elif btn_id == "redownload-btn":
            table = self.query_one("#history-table", DataTable)
            row = table.cursor_row
            if row is not None and 0 <= row < len(config.history):
                item = config.history[row]
                self.app.push_screen(ChapterScreen(item["name"], item["url"]))


class SettingsScreen(Screen):
    """设置页面"""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="settings-screen"):
            yield Static("⚙️ 设置", id="settings-title")
            with Horizontal():
                yield Static("保存目录:")
                yield Input(value=config.save_dir, id="save-dir-input")
            with Horizontal():
                yield Static("下载间隔(秒):")
                yield Input(value=str(config.default_sep), id="sep-input")
            with Horizontal():
                yield Button("保存", id="save-btn", variant="primary")
                yield Button("返回", id="back-btn")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "back-btn":
            self.app.switch_screen("main")
        elif btn_id == "save-btn":
            save_dir = self.query_one("#save-dir-input", Input).value.strip()
            sep_val = self.query_one("#sep-input", Input).value.strip()
            config.save_dir = save_dir
            try:
                config.default_sep = float(sep_val)
            except ValueError:
                self.notify("间隔时间必须是数字", severity="error")
                return
            config.save()
            self.notify("设置已保存")


class DownloadsScreen(Screen):
    """后台下载管理页面"""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="downloads-screen"):
            yield Static("📥 后台下载", id="downloads-title")
            yield DataTable(id="downloads-table")
            with Horizontal(id="downloads-actions"):
                yield Button("返回", id="back-btn")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#downloads-table", DataTable)
        table.add_columns("小说名", "进度", "状态")
        table.cursor_type = "row"
        self._refresh_table()
        # 每 0.5 秒刷新进度
        self.set_interval(0.5, self._refresh_table)

    def _refresh_table(self) -> None:
        downloads = self.app.active_downloads
        table = self.query_one("#downloads-table", DataTable)
        # 无下载时减少重绘：如果表格已经是空状态则跳过
        if not downloads:
            if not table.disabled:
                table.clear()
                table.add_row("暂无后台下载", "", "")
                table.disabled = True
            return
        table.clear()
        for name, info in downloads.items():
            progress = f"{info['current']} / {info['total']}"
            pct = info["current"] / info["total"] * 100 if info["total"] else 0
            status = f"下载中 ({pct:.0f}%)"
            table.add_row(name, progress, status)
        table.disabled = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.switch_screen("main")


class MainScreen(Screen):
    """主菜单页面"""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Container(id="main-screen"):
            yield Static("📖 Noval 小说下载器", id="main-title")
            yield Static("搜索 → 选择 → 下载，一气呵成", id="main-subtitle")
            with Vertical(id="main-menu"):
                yield Button("🔍  搜索小说", id="menu-search", variant="primary")
                yield Button("📚  下载历史", id="menu-history")
                yield Button("📥  后台下载", id="menu-downloads")
                yield Button("⚙️  设置", id="menu-settings")
                yield Button("🚪  退出", id="menu-exit")
        yield Footer()

    def on_mount(self) -> None:
        self._update_downloads_btn()

    def on_screen_resume(self) -> None:
        self._update_downloads_btn()

    def _update_downloads_btn(self) -> None:
        btn = self.query_one("#menu-downloads", Button)
        count = len(self.app.active_downloads)
        btn.label = f"📥  后台下载({count})" if count else "📥  后台下载"

    def on_button_pressed(self, event: Button.Pressed) -> None:
        menu = {
            "menu-search": "search",
            "menu-history": "history",
            "menu-downloads": "downloads",
            "menu-settings": "settings",
            "menu-exit": "exit",
        }
        action = menu.get(event.button.id)
        if action == "search":
            self.app.switch_screen("search")
        elif action == "history":
            self.app.switch_screen("history")
        elif action == "downloads":
            self.app.switch_screen("downloads")
        elif action == "settings":
            self.app.switch_screen("settings")
        elif action == "exit":
            self.app.exit()


class NovalApp(App):
    """Textual TUI 应用入口"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.active_downloads: Dict[str, dict] = {}


    CSS = """
    /* ---------- 基础配色 (Tokyo Night 风格暗色主题) ---------- */
    $primary: #7aa2f7;
    $primary-dark: #565f89;
    $accent: #bb9af7;
    $success: #9ece6a;
    $warning: #e0af68;
    $error: #f7768e;
    $surface: #1a1b26;
    $surface-lighten-1: #24283b;
    $surface-lighten-2: #414868;
    $text: #a9b1d6;
    $text-muted: #565f89;

    Screen {
        align: center middle;
        background: $surface;
    }

    Header {
        background: $surface-lighten-1;
        color: $text;
        text-style: bold;
    }

    Footer {
        background: $surface-lighten-1;
        color: $text-muted;
    }

    Input {
        border: tall $surface-lighten-2;
        background: $surface;
    }
    Input:focus {
        border: tall $primary;
    }

    Button {
        background: $surface-lighten-1;
        color: $text;
        border: tall $surface-lighten-2;
    }
    Button:hover {
        background: $surface-lighten-2;
        border: tall $primary;
    }
    Button:focus {
        border: tall $accent;
    }
    Button.primary {
        background: $primary;
        color: $surface;
        border: tall $primary;
        text-style: bold;
    }
    Button.primary:hover {
        background: #8db0ff;
        border: tall #8db0ff;
    }
    Button:disabled {
        background: $surface-lighten-1;
        color: $text-muted;
        border: tall $surface-lighten-1;
    }

    DataTable {
        background: $surface;
        border: tall $surface-lighten-2;
    }
    DataTable > .datatable--header {
        background: $surface-lighten-1;
        color: $primary;
        text-style: bold;
    }
    DataTable > .datatable--cursor {
        background: $surface-lighten-2;
        color: $accent;
        text-style: bold;
    }
    DataTable > .datatable--hover {
        background: $surface-lighten-1;
    }
    DataTable:focus {
        border: tall $primary;
    }

    ProgressBar {
        width: 100%;
    }

    Static {
        color: $text;
    }

    /* ---------- 主菜单 ---------- */
    #main-screen {
        width: 70;
        height: auto;
        border: round $primary-dark;
        background: $surface-lighten-1;
        padding: 2 4;
    }
    #main-title {
        text-align: center;
        margin-bottom: 1;
        color: $primary;
        text-style: bold;
    }
    #main-subtitle {
        text-align: center;
        margin-bottom: 2;
        color: $text-muted;
    }
    #main-menu {
        height: auto;
    }
    #main-menu Button {
        width: 100%;
        height: 3;
        margin: 1 0;
        text-style: bold;
    }

    /* ---------- 搜索页 ---------- */
    #search-screen {
        width: 100%;
        height: 100%;
        padding: 1 2;
    }
    #search-header {
        text-align: center;
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }
    #search-bar {
        height: auto;
        margin-bottom: 1;
    }
    #search-bar Input {
        width: 80%;
    }
    #search-bar Button {
        width: 20%;
    }
    #search-table {
        width: 100%;
        height: 1fr;
        border: tall $surface-lighten-2;
    }
    #search-actions {
        height: auto;
        margin-top: 1;
    }
    #search-actions Button {
        margin: 0 1;
    }

    /* ---------- 章节页 ---------- */
    #chapter-screen {
        width: 100%;
        height: 100%;
        padding: 1 2;
    }
    #chapter-title {
        text-align: center;
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }
    #chapter-status {
        text-align: center;
        color: $text-muted;
        margin-bottom: 1;
    }
    #chapter-table {
        width: 100%;
        height: 1fr;
        border: tall $surface-lighten-2;
    }
    #chapter-actions {
        height: auto;
        margin-top: 1;
    }
    #chapter-actions Button {
        margin: 0 1;
    }

    /* ---------- 下载页 ---------- */
    #download-screen {
        width: 100%;
        height: 100%;
        padding: 1 2;
        align: center middle;
    }
    #download-card {
        width: 80;
        height: auto;
        border: round $primary-dark;
        background: $surface-lighten-1;
        padding: 2 4;
        align: center middle;
    }
    #download-title {
        text-align: center;
        color: $primary;
        text-style: bold;
    }
    #download-subtitle {
        text-align: center;
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }
    #download-progress {
        margin: 2 0;
        width: 100%;
    }
    #download-status {
        text-align: center;
        color: $text-muted;
        margin-bottom: 1;
    }
    #download-log {
        text-align: center;
        color: $accent;
        margin-bottom: 2;
    }

    /* ---------- 后台下载页 ---------- */
    #downloads-screen {
        width: 100%;
        height: 100%;
        padding: 1 2;
    }
    #downloads-title {
        text-align: center;
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }
    #downloads-table {
        width: 100%;
        height: 1fr;
        border: tall $surface-lighten-2;
    }
    #downloads-actions {
        height: auto;
        margin-top: 1;
    }

    /* ---------- 历史页 ---------- */
    #history-screen {
        width: 100%;
        height: 100%;
        padding: 1 2;
    }
    #history-title {
        text-align: center;
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }
    #history-table {
        width: 100%;
        height: 1fr;
        border: tall $surface-lighten-2;
    }

    /* ---------- 设置页 ---------- */
    #settings-screen {
        width: 100%;
        height: 100%;
        padding: 1 2;
    }
    #settings-title {
        text-align: center;
        color: $primary;
        text-style: bold;
        margin-bottom: 2;
    }
    #settings-screen Horizontal {
        height: auto;
        margin: 1 0;
    }
    #settings-screen Static {
        width: 20;
        content-align: left middle;
        color: $text;
    }
    #settings-screen Input {
        width: 50;
    }

    /* ---------- 范围弹窗 ---------- */
    #range-dialog {
        width: 50;
        height: auto;
        border: round $accent;
        background: $surface-lighten-1;
        padding: 2 3;
        align: center middle;
    }
    #range-dialog Static {
        text-align: center;
        color: $primary;
        text-style: bold;
        margin-bottom: 1;
    }
    #range-dialog Input {
        width: 15;
        text-align: center;
    }
    """

    SCREENS = {
        "main": MainScreen,
        "search": SearchScreen,
        "history": HistoryScreen,
        "downloads": DownloadsScreen,
        "settings": SettingsScreen,
    }

    def on_mount(self) -> None:
        self.push_screen("main")


def run_tui() -> None:
    app = NovalApp()
    app.run()
