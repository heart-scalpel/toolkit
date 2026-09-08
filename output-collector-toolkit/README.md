# Output 收集器

生成和收集 Case 的完整操作步骤见 [用 Langfuse 生成 Case：操作指南](../langfuse-toolkit/docs/case-generation-guide.md)。

供内部成员整理 Langfuse Output 的工作台：登录后收集问题与画像、配对医生候选材料，导出 Argilla 标注所需的 CSV。每个账号有独立工作空间，内容自动保存到服务器，换电脑也能继续。

沿用 cozy_agent 的 FastAPI、uv、SQLAlchemy / SQLite、Alembic 和 Docker Compose 组织方式。当前为单实例、单 worker，前端与 API 同源，由一个容器提供；数据库直接保存在宿主机的 `backend/data/collector.db`。账号独立于 Langfuse、Argilla。每个人用自己的邮箱和密码自行注册，注册后直接进入工作空间，只能读取、修改和导出自己的材料。无需管理员开通、验证码或邮件验证。

## Docker 部署到服务器

以下命令从本工具目录执行：

```bash
cd output-collector-toolkit
cp .env.example .env
```

`.env.example` 已配置内网地址，复制后核对以下设置即可：

```dotenv
COLLECTOR_PUBLIC_ORIGIN=http://172.17.23.51:3722
COLLECTOR_COOKIE_SECURE=false
BIND_HOST=0.0.0.0
PORT=3722
```

这是内网服务器直接通过 IP 访问的配置，无需域名或反向代理。`COLLECTOR_PUBLIC_ORIGIN` 必须与浏览器地址一致，只含协议、IP / 域名和端口，不带路径。首次启动不需要设置管理员密码，服务启动后即可由成员各自注册。旧版部署切换前先按下方「从旧数据卷迁移」复制已有数据库，再重建容器。

```bash
docker compose --env-file .env -f docker/docker-compose-prod.yaml up -d --build
docker compose --env-file .env -f docker/docker-compose-prod.yaml ps
docker compose --env-file .env -f docker/docker-compose-prod.yaml logs --tail=100 collector
```

启动后访问 **http://172.17.23.51:3722**。`BIND_HOST=0.0.0.0` 让容器端口接受其他电脑访问；这些电脑需能连通该内网地址，服务器防火墙需允许内网访问 TCP 3722。HTTP 会明文传输登录信息与材料，这套配置用于可信内网。

Cookie 设置必须与访问协议一致：HTTP 使用 `COLLECTOR_COOKIE_SECURE=false`，HTTPS 使用 `true`；省略此项时后端按 `COLLECTOR_PUBLIC_ORIGIN` 自动判断。生产 Compose 会沿用 `.env` 的设置，账号认证和用户数据隔离仍然启用。HTTP 下浏览器可能不允许自动写入剪贴板，工具会弹出已选中的内容，按 Ctrl+C / ⌘C 手动复制即可。

### 可选：以后接入 HTTPS 域名

将 `.env` 改为 `COLLECTOR_PUBLIC_ORIGIN=https://collector.example.com`、`COLLECTOR_COOKIE_SECURE=true`、`BIND_HOST=127.0.0.1`，并把 HTTPS 反向代理接到 `127.0.0.1:3722`。例如在 Nginx 的对应 HTTPS `server` 中添加：

```nginx
location / {
    proxy_pass http://127.0.0.1:3722;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 10m;
    proxy_read_timeout 60s;
}
```

使用 HTTPS 反向代理时，访问地址使用独立域名的根路径。若反向代理也在 Docker 中，`127.0.0.1` 指向代理容器自身：应将两个容器接入同一受控 Docker 网络，再代理到收集器的 `8000` 端口；或使用已有的宿主机网关接入方式。Compose 项目名为 `output-collector-prod`，数据库挂载为 `../backend/data:/app/backend/data`，启动后可直接在本工具的 `backend/data/collector.db` 查看文件。Compose 已设置容器内的 `COLLECTOR_DATA_DIR`，无需在 `.env` 另填。

与 cozy_agent 的镜像保持一致，容器使用默认 root 用户；启动脚本创建数据目录，应用启动时执行数据库迁移，再提供注册和登录服务。健康检查访问 `/health`。首次构建需要下载 Python / uv 镜像和锁文件中的依赖；与 cozy_agent 一样默认使用清华 PyPI 源，可通过 `.env` 中的 `UV_INDEX_URL` 切换。

## 内部账号与使用流程

1. 打开页面，切换到「注册」，只填邮箱和自己设置的密码，点击「注册并进入」。邮箱不限制提供商，只检查基本格式并统一转为小写；不发送邮件、不校验邮箱是否实际存在，也没有验证码或管理员审批。密码为 1–128 个字符，无其他复杂度要求。
2. 注册成功会直接登录并创建空的个人工作空间。以后用相同邮箱和密码登录，可通过右上角「修改密码」自行修改。重复邮箱不能再次注册或重置已有密码；输错密码不会创建新账号。
3. 左侧填编号前缀（如 `S01`），粘贴第一个 Output，点「收下问题与画像」。`Q001` 会变成 `S01-Q001`；同场景新批次用 `S01-B02` 等新前缀。
4. 点「复制整批问诊输入」。默认选择刚收下的前缀，也可切到「全部问题」，一次复制 `{"cases":[...]}` 到第二个 Prompt 的 `case_input`。
5. 将第二个 Prompt 返回的 `{"reviews":[...]}` 粘贴到右侧，按完整 case_id 逐条匹配。兼容旧单条输出、多段 JSON 和 Playground 的 input/output 包装。
6. 点「下载 CSV」得到一条问题一行的标注表；「下载 JSON 备份」保留完整原文，可恢复到自己的账号。

两个成员可使用相同的 `S01-Q001`，数据互不影响。新注册账号都是普通成员，无权管理其他账号。服务器维护者仍能访问数据库和备份。

已有版本中的账号、密码、会话和材料会保留，原用户名仍可登录。已有管理员可继续使用原来的成员管理功能，新部署和日常注册均不依赖管理员账号。

接收、删除、恢复和清空都会保存到服务器，成功后才更新列表。重复内容跳过；同编号问题冲突时整批不写入；问诊材料更新需勾选替换。未关联材料会暂存并阻止 CSV 导出，缺少问诊材料的问题可导出并标记 `missing_review`，配齐后为 `draft_ready`；医生确认栏保持空白。

同账号打开多个窗口时，旧版本写入会被拒绝。发生冲突或网络中断后，先用「下载未确认保存的副本」保留该次内容，再点「加载服务器最新内容」，核对输入后重新接收。输入框会保留原文，服务器不会被旧窗口静默覆盖。网络请求失败时可能已提交但未收到响应，加载最新内容即可核对；重复接收相同材料会跳过。不同账号切换后不继承前一人的页面输入；服务器模式不把材料或登录凭证写进 localStorage。

默认单次保存上限 10 MiB，保存的是个人工作空间的完整快照，适合内部小团队分批整理。工作空间较大时可先导出备份，再清空开始下一批。`COLLECTOR_MAX_BODY_BYTES` 可调整上限，反向代理的请求大小限制应同步调整。

## 迁移原来的浏览器暂存

在原来双击打开的离线页面中下载 JSON 备份，登录服务器后点「恢复备份」导入。恢复会替换当前账号的收集内容，已有内容时会先提示确认。离线文件与服务器网址不是同一个浏览器存储位置，因此不会自动读取或上传旧暂存。

`index.html` 仍可单独双击，以 `file://` 离线模式打开；此模式无需账号、只保存在当前浏览器，不上传数据。通过 HTTP / HTTPS 打开时会使用服务器模式，需要配套后端，不再用普通静态文件服务器作为多人部署入口。

CSV 内画像、来源及追问保存为 JSON 单元格；pair_key 加编号前缀。CSV 对可能被表格解释为公式的开头加文本前缀；JSON 备份与复制问诊输入保持原文。本工具不调用模型，服务器模式只把材料提交到本工具的后端。

## 数据备份、升级与恢复

宿主机的 `backend/data/collector.db` 包含全部账号、会话和工作空间。个人 JSON 备份只包含该账号的材料，不含账号信息。数据库文件在容器重建或删除后仍会保留；仍需将数据库备份另存到服务器之外。

使用 SQLite 在线备份命令，包含 WAL 中的已提交数据：

```bash
docker compose --env-file .env -f docker/docker-compose-prod.yaml exec collector python -m app.manage backup-db /tmp/collector-backup.db
docker compose --env-file .env -f docker/docker-compose-prod.yaml cp collector:/tmp/collector-backup.db ./collector-backup.db
```

备份命令拒绝覆盖已有文件，再次备份时换一个文件名。妥善保管数据库备份，其中包含全部成员材料与密码哈希。

升级前备份，更新代码后再次运行 `up -d --build`，启动过程会执行 Alembic 迁移。停止服务保留数据：

```bash
docker compose --env-file .env -f docker/docker-compose-prod.yaml down
```

恢复整库时先停止服务，将备份复制到宿主机的 `backend/data/collector.db`，移除同目录下旧库配套的 `collector.db-wal` 和 `collector.db-shm`（仅在停止后操作），再启动服务。整库恢复会回退所有账号与材料，恢复后建议重新设置相关账号密码以撤销备份中的旧会话。

忘记密码时，由服务器维护者使用交互命令重置对应邮箱的密码；不通过邮件找回，密码不会出现在命令参数里：

```bash
docker compose --env-file .env -f docker/docker-compose-prod.yaml exec collector python -m app.manage reset-password person@example.com
```

### 从旧数据卷迁移

旧版生产数据在 `output-collector-prod_collector-data` 数据卷中，开发数据在 `output-collector-dev_collector-dev-data` 中。目录挂载不会自动读取旧卷。旧容器仍存在时，从工具目录执行以下命令，停服后复制整个数据目录，保留 SQLite 的 WAL 文件：

```bash
mkdir -p backend/data
test ! -e backend/data/collector.db && \
  docker compose --env-file .env -f docker/docker-compose-prod.yaml stop collector && \
  docker compose --env-file .env -f docker/docker-compose-prod.yaml cp collector:/app/backend/data/. ./backend/data/
```

确认 `backend/data/collector.db` 已出现后，再运行 `up -d --build`。上述命令会在目标数据库已存在时停止，避免覆盖；旧数据卷不会自动删除。开发环境迁移时，将命令中的 Compose 文件替换为 `docker/docker-compose-dev.yaml`。如果开发和生产旧卷都有数据，先选定要迁入本地目录的那一份，分别备份其余数据。

## 本地开发与验证

复制 `.env.example`；本地开发时将 `COLLECTOR_PUBLIC_ORIGIN` 改为 `http://localhost:3722`、`BIND_HOST` 改为 `127.0.0.1`，保留 `COLLECTOR_COOKIE_SECURE=false`：

```bash
cd backend
uv sync --locked
uv run uvicorn app.main:app --host 127.0.0.1 --port 3722 --workers 1 --reload
```

浏览器访问 `http://localhost:3722`。本地数据库位于 `backend/data/collector.db`，不提交到 Git。也可从工具目录启动开发容器：

```bash
docker compose --env-file .env -f docker/docker-compose-dev.yaml up --build
```

开发 Compose 沿用 cozy_agent 的方式挂载整个 `backend` 目录，容器内的 `.venv` 和 uv 缓存使用独立卷。启动脚本执行 `uv sync --locked` 同步依赖，再启动热重载；修改 HTML 后刷新页面。开发、生产和本地直接运行都使用 `backend/data/collector.db`，切换环境时先停止当前服务。若使用 IP 或改变端口访问，应同步修改 `COLLECTOR_PUBLIC_ORIGIN`。

验证：

```bash
cd backend
uv run pytest
uv run ruff check .
uv run ruff format --check .
cd ..
node --test tests/collector.test.cjs
```

接口测试使用临时数据库，覆盖邮箱注册 / 登录 / 退出、重复注册与并发注册、成员权限、相同编号的用户隔离、保存冲突、备份校验、会话撤销、旧数据库升级和数据库备份。Node 测试验证现有收集、配对、导出、恢复和 CSV 公式保护。

## Langfuse配置

第二个Prompt使用批量版 [System](../langfuse-toolkit/prompts/review.system.txt)、[User](../langfuse-toolkit/prompts/review.user.txt) 和 [输出Schema](../langfuse-toolkit/schemas/review-output.schema.json)。变量名保持 `case_input`。输入支持包含cases数组的对象或单条case，输出统一为reviews数组；每条材料仍只有原来的四项内容及case_id。

例如S01收下5条问题，复制后传入5条，返回5条，右侧一次接收。数据多时可按编号前缀分批操作；如果模型输出被截断，减少该次批量，不接收不完整JSON。工具会显示实际配齐数和待补数，不能仅凭模型返回成功判定整批完成。

## 包内文件

- `index.html`：登录页面、工作台、收集逻辑和两份内嵌 Schema；也支持单文件离线模式。
- `backend/app/`：配置、账号认证、个人存储 API、服务端校验和运维命令。
- `backend/migrations/`：Alembic 数据库迁移；`backend/uv.lock` 锁定依赖。
- `backend/tests/`、`tests/`：后端接口测试与收集逻辑回归测试。
- `backend/Dockerfile`、`docker/`：开发 / 生产镜像、Compose 和启动脚本。
- `.env.example`：配置模板；真实 `.env` 不提交、不打进镜像。

当前 QuestionOutput v2.0.0、ReviewOutput v4.0.0 与 Langfuse 工具包一致。后端直接读取随镜像发布的 HTML 内嵌 Schema，保持浏览器和 API 的字段校验一致；不依赖相邻工具包的运行环境。字段约定见 [CSV 字段映射](../langfuse-toolkit/docs/csv-fields.md)。
