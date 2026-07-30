"""SSH 远程执行辅助:python deploy/ssh_exec.py "命令" [超时秒]

运维通道:Windows 本机 openssh 无法非交互传密码,用 paramiko 建通道。
密码从环境变量 EVAC_SSH_PASS 读取,不落盘。
"""
import os
import sys

import paramiko

HOST = "121.41.172.35"
USER = "root"


def main() -> int:
    cmd = sys.argv[1]
    timeout = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0
    password = os.environ["EVAC_SSH_PASS"]

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=password, timeout=15)
    try:
        _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
        if out:
            print(out)
        if err:
            print("[stderr]", err, file=sys.stderr)
        return code
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
