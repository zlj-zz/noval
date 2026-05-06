from typing import Dict, Optional, Tuple
import os

from .utils import slice_list
from .downloader import Downloader
from .pretty import console, fiction_table, download_with_bar, Panel


def get_choice(num: int) -> int:
    range_str = f"1-{num}" if num > 1 else "1"
    while True:
        idx = input(f"input choice({range_str}):")
        try:
            idx = int(idx) - 1
            if not (0 <= idx < num):
                print("\033[1A\rerror: Index out of range.\033[K")
                continue
        except Exception:
            print("\033[1A\rerror: Please input a number.\033[K")
        else:
            break

    return idx


def _entry(
    fiction_name: str,
    dir_path: Optional[str] = None,
    sep: float = 0.0,
    chapter_range: Optional[Tuple[int, int]] = None,
    split: Optional[int] = None,
    append_mode: bool = False,
    search_mode: str = "bing",
) -> None:
    dl = Downloader(verify=False)

    # Search
    from .searcher import get_searcher
    from .const import SEARCH_LIST

    search_res = []
    with console.status(
        f"Search: [bold green]'{fiction_name}'...", spinner="shark"
    ) as _:
        if search_mode == "novel_site":
            searcher = get_searcher(
                search_mode, urls=SEARCH_LIST, extractor=dl._extractor,
                get_html_fn=dl.get_html
            )
        else:
            searcher = get_searcher(search_mode)
        search_res = searcher.search(fiction_name)

    if not search_res:
        console.print("[red]Can't get search result page.")
        return

    # Show search result.
    console.print(fiction_table(search_res))

    # Choice.
    idx = get_choice(len(search_res))

    # Show choice result.
    real_name = search_res[idx][0].split("|")[0]
    real_path = os.path.join(dir_path, real_name) if dir_path else real_name
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)

    next_url = search_res[idx][1]
    console.print(
        Panel(
            f"[yellow]{real_name}[/yellow], {next_url}",
            title="Selected",
            expand=False,
        )
    )

    # Get chapters.
    chapters = dl.get_chapters(next_url)
    if not chapters:
        console.print("[red]No chapter found!")
        return

    chapter_display_str = f"[Total chapters {len(chapters)}]"
    console.print(f"{chapter_display_str:=^100}")

    if chapter_range:
        chapters = chapters[chapter_range[0] - 1 : chapter_range[1] - 1]

    # Download
    if split and split > 1:
        for part_id, part_res in enumerate(
            slice_list(chapters, len(chapters) // split + 1), start=1
        ):
            download_with_bar(
                dl.download_chapters(
                    part_res,
                    f"{real_path}.txt".replace(".txt", f"_{part_id}.txt"),
                    sep,
                    append_mode,
                ),
                len(part_res),
                f"[green bold]Download part {part_id}...",
                f"[green bold]Part {part_id} downloaded",
            )
    else:
        download_with_bar(
            dl.download_chapters(
                chapters,
                f"{real_path}.txt",
                sep,
                append_mode,
            ),
            len(chapters),
            "[green bold]Download...",
            "[green bold]Downloaded",
        )


def entry(conf: Dict) -> None:
    if conf.get("non_interactive"):
        console.print(conf)
        try:
            _entry(**conf)
            console.print("[green u]End ^.^")
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Noval Manual Stop.")
    else:
        from .tui import run_tui

        run_tui()
