"""
HBPU Agent Student Client - 配置管理模块

本模块定义了学生客户端连接服务器所需的基本配置参数，包括：
.  SERVER_URL: WebSocket 服务器的连接地址，学生客户端将通过该地址与服务器建立通信。
.  RECONNECT_DELAY: 当客户端与服务器的连接意外断开时，客户端在尝试重新连接之前等待的时间（以秒为单位）。这有助于避免频繁的重连尝试，给服务器和网络带来压力。
.  HEARTBEAT_INTERVAL: 客户端发送心跳包的时间间隔（以秒为单位）。心跳包用于向服务器确认客户端仍然在线和活跃，帮助服务器及时发现断开的连接。
.  MAX_RECONNECT_ATTEMPTS: 当客户端掉线后，允许客户端尝试重新连接的最大次数。超过这个次数后，客户端将停止尝试重新连接，可能需要用户手动干预。

作者: Sacire
"""
SERVER_URL = "ws://localhost:8000/ws"   # WebSocket 服务器的连接地址
RECONNECT_DELAY = 5                     # 断开连接后，尝试重新连接前的延迟等待时间（单位：秒）
HEARTBEAT_INTERVAL = 30                 # 心跳包的发送间隔时间，用于向服务器确认客户端处于在线/活跃状态（单位：秒）
MAX_RECONNECT_ATTEMPTS = 10             # 掉线后允许客户端尝试重新连接的最大次数       