from typing import Dict
import os, threading
from urllib.parse import urlencode

from noval.downloader import Downloader
from noval.searcher import DuckDuckGoSearcher
from .utils import encode64, decode64, local_exist, key2file
from .code import *

try:
    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse, HTMLResponse
    from fastapi.middleware.cors import CORSMiddleware
except ModuleNotFoundError:
    print("Use 'pip install fastapi' to install fastapi first.")
    exit(1)


dr = Downloader(verify=False)
_searcher = DuckDuckGoSearcher()
app = FastAPI()

# CORS allow any host.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

curr_crawl_idx: Dict[str, int] = {}
total_dict: Dict[str, int] = {}

dir_path = os.path.dirname(os.path.abspath("."))
print(f"::{dir_path}")
# dir_path = f"{dir_path}/.."

encodekey = lambda fname, url: encode64(f"{fname}@@@{url}")
decodekey = lambda key: decode64(key).split("@@@")


@app.get("/")
def index():
    indexfile = os.path.join(dir_path, "index.html")
    with open(indexfile) as f:
        html_string = f.read()
        return HTMLResponse(html_string)


@app.get("/fiction")
def get_fictions(name: str):
    """Get fiction list follow name."""
    data = {}

    if name is not None:
        idx = 0
        for msg_string, url in _searcher.search(name):
            parts = msg_string.split("|")
            fname = parts[0] if parts else "Unknown"
            dt = parts[1] if len(parts) > 1 else ""
            info = parts[2] if len(parts) > 2 else ""
            key = encodekey(fname, url)

            data[idx] = {"name": fname, "date": dt, "info": info, "key": key}
            idx += 1

    return {"data": data}


@app.get("/chapters")
def get_chapters(key: str):
    """Get fiction chapters list."""
    return {"data": dr.get_chapters(decodekey(key)[1])}


@app.get("/crawl")
def crawl(key: str, force: bool = False):
    """Try to crawl a fiction."""
    global curr_chapter_idx

    # process fiction name
    try:
        fname, target_url = decodekey(key)
    except UnicodeDecodeError:
        print(f":: The key is not right. '{key}'")
        return_data = {
            "total": -1,
            "key": "ERROR_KEY",
            "exist": False,
            "status": CrawlStatus.NONE,
        }
    else:
        filepath = key2file(key, dir_path)
        print("::", target_url, filepath)

        has_file: bool = local_exist(filepath)

        # init data query.
        return_data = {
            "total": -1,
            "key": key,
            "exist": has_file,
            "status": CrawlStatus.NONE,
        }

        # check is crawling now.
        is_crawling: bool = curr_crawl_idx.get(key, NO_STATUS) not in {
            NO_STATUS,
            FINISH_STATUS,
        }

        # if file exist or crawling, then don't repeat.
        if has_file and not force:
            pass
        elif is_crawling:
            return_data["status"] = CrawlStatus.RUNNING
            return_data["total"] = total_dict.get(key, -1)
        else:
            # get fiction chapters
            chapters = dr.get_chapters(target_url)
            print(chapters)

            if chapters:
                return_data["total"] = total_dict[key] = len(chapters)
                return_data["status"] = CrawlStatus.START
                curr_crawl_idx[key] = 0

                def _c():
                    for idx, msg in enumerate(dr.download_chapters(chapters, filepath)):
                        print(msg)
                        curr_crawl_idx[key] = idx
                    curr_crawl_idx[key] = FINISH_STATUS

                # start thread download.
                threading.Thread(target=_c, daemon=True).start()

    # data = {'total': 1000, 'key':''}
    return {"data": return_data}


@app.get("/crawl_status")
def get_crawl_status(key: str):
    """Get current crawl progress of key."""
    global curr_crawl_idx

    curr = curr_crawl_idx.get(key, NO_STATUS)

    # Only check whether file already exist when `NO_STATUS`. This ensures that the IO
    # query is executed at most once.
    if curr == NO_STATUS and local_exist(key2file(key, dir_path)):
        curr = EXIST_STATUS

    return {
        "data": {"current": curr},
    }


@app.get("/download")
def download(key: str):
    """Download fiction follow key."""
    fname, url = decodekey(key)
    filename = f"{fname}.txt"
    filepath = os.path.join(dir_path, f"{key}.txt")

    def _iter_file():
        with open(filepath) as file_like:
            yield from file_like

    headers = {"Content-Disposition": f"attachment;{urlencode({'filename':filename})}"}
    return StreamingResponse(
        _iter_file(), headers=headers, media_type="text/plain; charset=utf-8"
    )


# uvicorn api:app --reload
