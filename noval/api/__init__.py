"""Noval Api

This is the web API module about noval.
It encapsulates the functions in noval and provides a set of interfaces for
downloading novels. Can be used to build their own applications. Build with
`fastapi`(https://github.com/tiangolo/fastapi). Support quick start in terminal.

Start:
        python3 -m noval.api

Support Api:
        /fiction?name=[name]
        Get fiction list.

        /chapters?key=[key]
        Get the chapters list of key of one fiction.

        /crawl?key=[key]
        Try to crawl a fiction according to the key.

        /crawl_status?key=[key]
        Get current crawl progress of key.

        /download?key=[key]
        Download the fiction from remote according to the key.
"""
