import os, sys

# 'setup.py publish' shortcut.
if sys.argv[-1] == "publish":
    os.system("python setup.py sdist bdist_wheel")
    os.system("twine upload dist/*")
    sys.exit()

PYTHON_VERSION = sys.version_info[:3]
if PYTHON_VERSION < (3, 8, 0):
    print("Not support python version < 3.8")
    exit(0)

try:
    LONG_DESCRIPTION = open("README.md", encoding="utf-8").read()
except Exception:
    LONG_DESCRIPTION = """# novel

Configurable novel Downloader.
```
    """

from setuptools import setup, find_packages
import noval

setup(
    name=noval.__project__,
    version=noval.__version__,
    author=noval.__author__,
    author_email=noval.__email__,
    description="Configurable novel Downloader.",
    long_description=LONG_DESCRIPTION,
    long_description_content_type="text/markdown",
    url=noval.__url__,
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Topic :: System :: Shells",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX",
        "Operating System :: Unix",
        "Operating System :: MacOS",
        "Operating System :: Microsoft :: Windows",
    ],
    data_files=["noval_conf.json"],
    install_requires=["requests", "lxml"],
    entry_points="""
        [console_scripts]
        noval=noval.fiction_downloader:main
    """,
    python_requires=">=3.8",
)