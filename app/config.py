import os

from dotenv import load_dotenv


load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-key")
    NETUID = int(os.getenv("NETUID", "120"))
    NETWORK = os.getenv("BT_NETWORK", "finney")
    REFRESH_SECONDS = int(os.getenv("REFRESH_SECONDS", "120"))
    BLOCKS_PER_DAY = int(os.getenv("BLOCKS_PER_DAY", "7200"))
    CACHE_SECONDS = int(os.getenv("CACHE_SECONDS", "120"))
    METAGRAPH_CACHE_SECONDS = int(os.getenv("METAGRAPH_CACHE_SECONDS", "120"))
    METAGRAPH_RETRY_SECONDS = int(os.getenv("METAGRAPH_RETRY_SECONDS", "90"))
