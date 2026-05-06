from typing import Dict, Generator, List, Literal, Optional, Sequence, Tuple
import time
import textwrap
import urllib3

from .extractor import Extractor
from .const import HEADERS, DEFAULT_HTM

import requests
import logging

# 诊断日志
logger = logging.getLogger("noval.downloader")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    _fh = logging.FileHandler("/tmp/noval_download.log", mode="a")
    _fh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(_fh)


class DownloaderError(Exception):
    """Error class of ~Downloader."""

    pass


class Downloader:
    """Fiction download API class."""

    def __init__(
        self,
        timeout: int = 10,
        retry: int = 5,
        encoding: str = "utf-8",
        verify: bool = True,
        extractor_class: Sequence[Extractor] = Extractor,
    ) -> None:
        self.timeout = timeout
        self.retry = retry
        self.encoding = encoding
        self.verify = verify
        if not verify:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        self._extractor: Extractor = extractor_class()
        self._scraper: requests.Session = requests.Session()

    #########
    # tools
    #########
    def _get_html(
        self,
        url: str,
        retry: int,
        mode: Literal["get", "post"] = "get",
        data: Optional[Dict] = None,
    ) -> Tuple[str, str]:
        html, true_url = "", ""
        logger.debug(f"[GET] start {url} retry={retry}")
        t0 = time.time()

        try:
            if mode == "get":
                resp = self._scraper.get(
                    url, timeout=self.timeout, verify=self.verify, headers=HEADERS
                )
            elif mode == "post":
                resp = self._scraper.post(
                    url, data, timeout=self.timeout, verify=self.verify, headers=HEADERS
                )
            else:
                raise DownloaderError(
                    "request method please give 'get' or 'post'."
                ) from None
        except (
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.ReadTimeout,
        ) as exc:
            logger.debug(f"[GET] timeout/error {url} {type(exc).__name__}")
            if retry > 0:
                return self._get_html(url, retry - 1)
        except requests.exceptions.SSLError:
            raise DownloaderError(
                "Get SSLError, should set `verify` to False."
            ) from None
        except requests.exceptions.RequestException as exc:
            logger.debug(f"[GET] request error {url} {type(exc).__name__}: {exc}")
        else:
            elapsed = time.time() - t0
            logger.debug(
                f"[GET] done {url} status={resp.status_code} len={len(resp.content)} t={elapsed:.2f}s"
            )
            # 尝试多种编码解码，适配中文站点常见的 gbk/gb2312
            for enc in (self.encoding, "utf-8", "gbk", "gb2312", "gb18030", "big5"):
                try:
                    html = resp.content.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                html = resp.content.decode(self.encoding, errors="replace")
            true_url = resp.url

        return html, true_url

    def get_html(self, url: str):
        return self._get_html(url, self.retry)

    def write(self, file: str, content: str, mode: str = "w") -> None:
        """Write content to file."""
        with open(file, mode=mode) as fp:
            fp.write(content)

    def clear(self, file: str) -> None:
        """Clear the fiction file."""
        with open(file, mode="w") as _:
            pass

    ########
    # step
    ########
    def get_chapters(self, next_url: str) -> List:
        """Return a chapter list with name and url."""

        extractor = self._extractor

        html, u = self.get_html(next_url)
        res = extractor.extract_chapters(html or DEFAULT_HTM, u)
        # print(res)

        if not res:
            if next_url := extractor.extract_detail(html or DEFAULT_HTM, u):
                # print(f"Get next url: {next_url}")
                html, u = self.get_html(next_url)
                res = extractor.extract_chapters(html or DEFAULT_HTM, u)

        return res

    def download_chapters(
        self,
        down_chapters: List[Tuple[str, str]],
        path: str,
        sep: float = 0.0,
        append_mode: bool = False,
    ) -> Generator[Tuple[str, str], bool, None]:
        """
        Yield (name, url) when finish once downloading.
        Yield (None, None) when get html failed, re-try when receive True else closure.

        Args:
            down_chapters (List[Tuple[str, str]]): chapters list of need download.
            path (str): saving dir path.
            sep (float, optional): sleep time for each download. Defaults to 0.0.
            append_mode (bool, optional): whether download with append mode. Defaults to False.
        """

        extractor = self._extractor

        # Clear the file, if already exist and not append mode.
        not append_mode and self.clear(path)

        # Avoid frequent creation and destruction of IO.
        with open(path, mode="a+") as f:
            for chapter_name, url in down_chapters:
                # console.print(chapter_name, url)

                while True:
                    html, _ = self.get_html(url)

                    if html:
                        break

                    flag = yield (None, None)
                    if flag:
                        continue
                    else:
                        return

                content = extractor.extract_content(html)

                if not content:
                    continue

                chapter_content = f"{chapter_name}\n{textwrap.indent(content,'  ')}\n\n"
                f.write(chapter_content)

                time.sleep(sep)
                yield chapter_name, url
