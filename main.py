#!/usr/bin/env python3

#
# Stupid simple multiplexer socket server.
#   1. Remote reverse shell connects to MainServer.
#   2. MainServer opens local ProxyHandler.
#   3. Local client connects to ProxyHandler.
#   4. ProxyHandler transfers between local and remote clients.
#
# Why?
#   - MainServer can continue listening on same port.
#   - ProxyHandler keeps remote open if local disconnects.
#
# Tasks:
#   - Use async for socket operations in ProxyHandler.
#   - Improve error handling (not all cases caught).
#

import errno
import fcntl
import select
import shlex
import socket
import socketserver
import struct
import threading


LIFNAME = "tun0"
LPORT = 443

SESSION = 1
SESSIONS = 0


class MainServer(socketserver.ThreadingTCPServer):

    allow_reuse_address = True
    daemon_threads = True


class ProxyHandler(socketserver.BaseRequestHandler):

    def setup(self):
        global SESSION, SESSIONS
        self.session = SESSION
        SESSION += 1
        SESSIONS += 1

    def finish(self):
        global SESSIONS
        SESSIONS -= 1

    def handle(self):
        #
        # Initialize proxy.
        #
        proxy = socket.create_server(("127.0.0.1", 0), reuse_port=True)
        proxy.setblocking(False)
        PHOST, PPORT = proxy.getsockname()
        print(f"(+) [#{self.session}] Remote : {self.client_address} -> nc {PHOST} {PPORT}")

        #
        # Main proxy loop.
        #
        remote_to_local = b""
        local_to_remote = b""
        remote, local = self.request, None
        remote_off, local_off = False, False
        check_read = [remote, proxy]
        while remote:
            #
            # Read data and accept connections.
            #
            can_read, _, _ = select.select(check_read, [], [])
            if proxy in can_read:
                local, local_address = proxy.accept()
                check_read.append(local)
                check_read.remove(proxy)
                print(f"(>) [#{self.session}] Local  : {local_address}")
            if remote in can_read:
                data = remote.recv(4096)
                if not data:
                    remote_off = True
                else:
                    remote_to_local += data
            if local in can_read:
                data = local.recv(4096)
                if not data:
                    local_off = True
                else:
                    local_to_remote += data

            #
            # Attempt to write buffered data.
            #
            if remote and local_to_remote:
                try:
                    remote.sendall(local_to_remote)
                    local_to_remote = b""
                except:
                    remote_off = True
            if local and remote_to_local:
                try:
                    local.sendall(remote_to_local)
                    remote_to_local = b""
                except:
                    local_off = True

            #
            # Handle closed connections.
            #
            if local_off:
                check_read.remove(local)
                check_read.append(proxy)
                local.close()
                local = None
                local_off = False
                print(f"(!) [#{self.session}] Local  : disconnected")
            if remote_off:
                check_read.remove(remote)
                remote.close()
                remote = None
                remote_off = False
                print(f"(!) [#{self.session}] Remote : disconnected")
            if not (remote or local or remote_to_local or local_to_remote):
                print(f"(!) [#{self.session}] Session closed")
                break

        proxy.close()


def main():
    print()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        packed = struct.pack("256s", LIFNAME.encode())
        LHOST = fcntl.ioctl(s.fileno(), 0x8915, packed)  # SIOCGIFADDR
        LHOST = socket.inet_ntoa(LHOST[20:24])
    print(f"(+) LHOST = {LHOST} ({LIFNAME})")
    print(f"(+) LPORT = {LPORT}")
    print()

    listener = MainServer((LHOST, LPORT), ProxyHandler)
    lthread = threading.Thread(target=listener.serve_forever)
    lthread.start()
    CONFIRMED = False
    while True:
        try:
            lthread.join() # Never happens.
        except KeyboardInterrupt:
            print("\r", end="") # Stop ^C from popping up in terminal.
            if not CONFIRMED and SESSIONS:
                print("(>) There are still open sessions, press Ctrl+C again to force quit")
                CONFIRMED = True
                continue
            else:
                print("(>) Keyboard interrupt received, exiting...")
                break
        finally:
            listener.shutdown()
            listener.server_close()


if __name__ == "__main__":
    main()