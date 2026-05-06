# sourcery skip: use-fstring-for-formatting
import os, sys, re
from setuptools import setup, find_packages
import noval

# 'setup.py publish' shortcut.
if sys.argv[-1] == "release":
    os.system(f"git commit -am 'Bump to {noval.__version__}'")
    os.system(f"git tag {noval.__version__}")
    os.system("git push")
    os.system("git push --tags")

    if os.path.exists("dist"):
        os.system("rm -rf dist/*")
    os.system("python3 setup.py sdist bdist_wheel")
    os.system("twine upload dist/*")
    sys.exit(0)

elif sys.argv[-1] == "uninstall":
    os.system("python3 -m pip uninstall noval")
    sys.exit(0)

PYTHON_VERSION = sys.version_info[:3]
SUPPORT_VERSION = (3, 8, 0)
if PYTHON_VERSION < SUPPORT_VERSION:
    print("Not support python version < {}".format(".".join(SUPPORT_VERSION)))
    exit(0)

try:
    LONG_DESCRIPTION = open("README.md", encoding="utf-8").read()
    LONG_DESCRIPTION = re.sub(
        r"\((\.)([a-zA-Z/.]+\.(?:png|jpg|jpeg))\)",
        r"(https://github.com/zlj-zz/noval/blob/main\2)",
        LONG_DESCRIPTION,
    )
except Exception:
    LONG_DESCRIPTION = """# noval

Configurable novel Downloader.

> Can not load description.
```
    """


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
    data_files=[("api", ["noval/api/index.html"])],
    install_requires=["requests", "lxml", "numpy", "rich", "textual", "cloudscraper"],
    entry_points="""
        [console_scripts]
        noval=noval.main:main
    """,
    python_requires=">=3.8",
)
