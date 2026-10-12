# 舞蹈练习 · TVShare

家长用手机网页上传舞蹈视频，孩子在电视上用遥控器选视频跟着练。

```
手机浏览器 ──上传/管理──▶  云服务器（FastAPI + ffmpeg）  ◀──浏览/播放── 电视 App（Android TV）
```

| 部分 | 目录 | 说明 |
|---|---|---|
| 服务器 + 手机网页 | `server/` | Python FastAPI、SQLite、ffmpeg。手机网页在同一个服务里，不需要单独部署 |
| 电视 App | `tv/` | Kotlin + Compose for TV + Media3 播放器，安装包约 10MB |

## 功能

**手机网页**
- 家庭密码登录
- 一次选多个视频上传，**分片断点续传**，网络断了会自动接着传
- 分类管理（如「中国舞」「爵士」「本周作业」），可调整顺序
- 改名、换分类、删除、预览
- 「绑定电视」：输入电视上显示的 6 位配对码

**服务器**
- 上传后自动转成电视都能播的 H.264 MP4（iPhone 的 HEVC / HDR / .mov 都会处理），并生成封面
- 已经是 H.264 的视频只重新封装，不重新编码，处理很快

**电视 App**
- 首次打开显示配对码，家长手机上输一下就绑定好了，**不用在电视上输密码**
- 按分类浏览，遥控器左右切换分类
- 播放器专为练舞设计：
  - **镜像**：左右翻转画面，孩子照着做方向就和老师一致（像对着镜子）。开启后会记住
  - **慢速**：1.0x / 0.75x / 0.5x，声音音调不变
  - **循环**：单个视频反复播放
  - 菜单隐藏时：遥控器 ← → 快退/快进 5 秒，OK 暂停/播放，↑ ↓ 打开菜单，返回键关闭菜单/退出

## 一、部署服务器（云服务器）

需要一台 Linux 云服务器（阿里云 / 腾讯云轻量服务器即可，1 核 2G 起）。

```bash
# 1. 安装 Docker（以 Ubuntu 为例）
curl -fsSL https://get.docker.com | sh

# 2. 把整个项目上传到服务器，进入目录
cd TVShare
cp .env.example .env
nano .env            # 设置 TVSHARE_PASSWORD

# 3. 启动
docker compose up -d --build
```

4. 在云服务器控制台的**安全组 / 防火墙**里放行 TCP **8000** 端口。
5. 手机浏览器打开 `http://服务器公网IP:8000`，用家庭密码登录。

视频、封面和数据库都保存在 `./data` 目录，备份这个目录就行。

### 带宽要注意

云服务器的**出网带宽**决定电视播放是否流畅（上传通常不限速）：

| 服务器带宽 | 建议 |
|---|---|
| 5Mbps 以上 | 默认 1080p 即可 |
| 3~5Mbps | 在 `.env` 里设 `TVSHARE_MAX_HEIGHT=720`，然后 `docker compose up -d` |
| 低于 3Mbps | 建议升级带宽，或设为 540 |

修改 `TVSHARE_MAX_HEIGHT` 只影响之后上传的视频。

### 可选：用已有证书 + 独立端口 + 随机路径（不新增域名）

服务器上已经有某个域名的证书时，可以给 TVShare 单独开一个 nginx 站点：换一个端口，复用同一张证书，再加一段随机路径，和其他站点互不影响。例如 `https://example.com:12584/<随机串>/`。网页用的都是相对路径，电视端按"地址 + 路径"拼接，都支持前缀。

1. `.env` 里加 `TVSHARE_BIND=127.0.0.1`、`TVSHARE_SECURE_COOKIE=1`、`TVSHARE_TRUSTED_PROXIES=*`
2. 新建 `/etc/nginx/conf.d/tvshare.conf`（随机串用 `openssl rand -hex 12` 生成）：

   ```nginx
   server {
       listen 12584 ssl http2;
       server_name example.com;
       ssl_certificate     /etc/letsencrypt/live/example.com/fullchain.pem;
       ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

       location = /<随机串> { return 301 /<随机串>/; }
       location /<随机串>/ {
           proxy_pass http://127.0.0.1:8000/;
           proxy_set_header Host $host;
           proxy_set_header X-Forwarded-For $remote_addr;
           proxy_set_header X-Forwarded-Proto $scheme;
           proxy_cookie_path / /<随机串>/;
           proxy_buffering off;
           proxy_request_buffering off;
           client_max_body_size 20m;
           proxy_read_timeout 300s;
           proxy_send_timeout 300s;
       }
       location / { return 404; }
   }
   ```
3. `nginx -t && systemctl reload nginx`，并在云服务器安全组放行这个端口
4. 打包电视端时 `-Ptvshare.serverUrl=https://example.com:12584/<随机串>`

### 可选：域名 + HTTPS

用域名访问更方便，也更安全（家庭密码不会明文传输）。在服务器上用 Caddy 反向代理，会自动申请证书：

```
# /etc/caddy/Caddyfile
dance.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

同时在 `docker-compose.yml` 的 environment 里加：

```yaml
      TVSHARE_SECURE_COOKIE: "1"
      TVSHARE_TRUSTED_PROXIES: "*"   # 让服务器识别真实 IP，用于登录防暴力破解
```

并把端口改成只监听本机：`"127.0.0.1:8000:8000"`。

> 国内服务器使用域名的 80/443 端口需要先完成 ICP 备案；只用 `IP:8000` 访问则不需要。

## 二、打包电视 App

需要 JDK 17+ 和 Android SDK（装了 Android Studio 就有）。

```bash
cd tv
# 把服务器地址打进安装包，电视打开后直接显示配对码（推荐）
./gradlew assembleRelease -Ptvshare.serverUrl=http://服务器公网IP:8000
```

Windows 用 `gradlew.bat`。生成的安装包在：

```
tv/app/build/outputs/apk/release/app-release.apk
```

不填 `tvshare.serverUrl` 也可以，电视首次打开时会让你用遥控器输入服务器地址。

### 安装到电视

任选一种：
- **U 盘**：把 apk 拷到 U 盘插电视，用电视自带的文件管理器打开安装（需在电视设置里允许"安装未知来源应用"）
- **adb**：电视打开开发者模式和 USB/网络调试后，`adb connect 电视IP` → `adb install app-release.apk`
- **当贝助手等**：通过手机推送 apk 到电视

安装后在电视桌面找到「舞蹈练习」。

## 三、日常使用

1. **第一次**：电视打开「舞蹈练习」→ 屏幕显示 6 位配对码 → 手机网页点「📺 绑定电视」输入配对码
2. **上传**：手机网页点「＋ 上传视频」→ 选视频、选分类 → 开始上传。上传完会显示"处理中"，一般几十秒到几分钟（取决于视频长度）
3. **练习**：孩子在电视上选分类 → 选视频 → 播放。按 ↑ 打开菜单可以开镜像、调慢速、开循环

## 本地开发

```bash
# 服务器（需要本机装 ffmpeg）
cd server
pip install -r requirements.txt pytest httpx
TVSHARE_PASSWORD=test python -m app.main      # http://localhost:8000
python -m pytest                              # 运行测试

# 电视端：用 Android Studio 打开 tv/ 目录，在 Android TV 模拟器里运行
# 模拟器访问本机服务器的地址是 http://10.0.2.2:8000
```

### 服务器配置项（环境变量）

| 变量 | 默认 | 说明 |
|---|---|---|
| `TVSHARE_PASSWORD` | 必填 | 家庭密码。修改后所有手机和电视都需要重新登录/配对 |
| `TVSHARE_DATA_DIR` | `./data` | 数据目录 |
| `TVSHARE_PORT` | `8000` | 端口 |
| `TVSHARE_MAX_HEIGHT` | `1080` | 转码后画面短边上限 |
| `TVSHARE_FFMPEG_THREADS` | `0`（自动） | ffmpeg 每个环节用几个线程；小服务器建议 `1` |
| `TVSHARE_CPUS` | `0`（不限制） | 容器最多用几个 CPU 核（docker compose 生效）；小服务器建议 `1`，转码时不会把整台机器拖死 |
| `TVSHARE_SECURE_COOKIE` | `0` | 走 HTTPS 时设为 `1` |
| `TVSHARE_TRUSTED_PROXIES` | `127.0.0.1` | 可信反向代理 IP |

### 接口一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/login` | 密码登录，返回 token 并写 cookie |
| GET/POST/PATCH/DELETE | `/api/categories[/{id}]` | 分类 |
| GET/PATCH/DELETE | `/api/videos[/{id}]` | 视频；`POST /api/videos/{id}/retry` 重试失败的处理 |
| POST → PUT → POST | `/api/uploads` → `/api/uploads/{id}?offset=` → `/api/uploads/{id}/complete` | 分片断点续传 |
| POST / GET | `/api/pair` / `/api/pair/{pair_id}` | 电视获取配对码 / 轮询结果 |
| POST | `/api/pair/confirm` | 手机确认配对码 |
| GET | `/media/videos/{id}.mp4`、`/media/thumbs/{id}.jpg` | 视频（支持 Range 拖动）和封面 |

除登录和配对外，所有接口都需要 `Authorization: Bearer <token>` 或登录 cookie。
