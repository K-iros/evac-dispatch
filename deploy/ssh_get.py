"""SFTP 下载辅助:python deploy/ssh_get.py 远端路径 本地文件

密码从环境变量 EVAC_SSH_PASS 读取,与 ssh_exec.py 同一通道。
"""
import os
import sys

import paramiko

HOST = "121.41.172.35"
USER = "root"


def main() -> int:
    remote, local = sys.argv[1], sys.argv[2]
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=os.environ["EVAC_SSH_PASS"], timeout=15)
    try:
        sftp = client.open_sftp()
        sftp.get(remote, local)
        print(f"downloaded {remote} -> {local}")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
