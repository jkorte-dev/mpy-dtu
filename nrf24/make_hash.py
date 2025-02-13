import binascii
import hashlib
import json
import os

# mkdir -p package/5/nrf24/
# mpy-cross -b 5 -o package/5/nrf24/nrf24.mpy src/nrf24.py
# mkdir -p package/6/nrf24/
# mpy-cross -b 6 -o package/6/nrf24/nrf24.mpy src/nrf24.py
# mkdir -p package/py/nrf24/
# cp src/nrf24.py package/py/nrf24/nrf24.py


for path in ("package/5/nrf24/nrf24.mpy", "package/6/nrf24/nrf24.mpy", "package/py/nrf24/nrf24.py"):
    with open(path, "rb") as f:
        b = f.read()
    hs256 = hashlib.sha256(b)
    short_hash = str(binascii.hexlify(hs256.digest())[:8], "utf-8")
    #print(path, short_hash)
    target_path = path.split('/')[3]
    #index = "http://192.168.178.46"
    file_url = "file/{}/{}".format( short_hash[:2], short_hash)
    file_dir = f"file/{short_hash[:2]}"
    print(path, file_url)
    if "file" not in os.listdir():
        os.mkdir("file")
    if short_hash[:2] not in os.listdir("file"):
        os.mkdir(file_dir)
    with open(file_url, "wb") as f:
        f.write(b)
    package_json = {"v": 1, "hashes": [[target_path, short_hash]], "version": "0.1.0"}
    json_path = path.replace(target_path, "") + 'latest.json'
    print(package_json)
    with open(json_path, "w") as f:
        json.dump(package_json, f)
        f.write("\n")

