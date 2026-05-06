import warnings

warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

from .args import main

if __name__ == "__main__":
    main()
