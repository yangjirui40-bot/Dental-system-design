# 本地运行与部署

## 环境

需要 Docker Engine 与 Compose、Node.js 22、npm，以及用于小程序构建的微信开发者工具。仓库的 `app/` 是项目根目录。PostgreSQL、Django API、网页由 `app/compose.yaml` 启动。微信小程序使用同一 API，并通过 `app/network/wechat-gateway/` 的云函数访问。

## 本地网页与后端

```bash
cd app
cp .env.example .env
# 在 .env 中设置强随机 POSTGRES_PASSWORD 和 SECRET_KEY，并核对本地 ALLOWED_HOSTS、CORS_ORIGINS
docker compose up -d --build --wait db api web
curl --fail http://127.0.0.1:8080/healthz
```

打开 http://localhost:8080/。首次运行应按实际用途初始化账号；公开仓库不提供生产账号、私钥或数据库备份。教学数据使用 `app/deploy/teaching/` 中的独立部署与合成数据脚本，不要将演示账号导入真实运营库。

## 构建前端

```bash
cd app/frontend
npm ci
npm run typecheck
npm run build:h5
npm run build:mp-weixin
```

网页产物位于 `frontend/dist/build/h5`，微信产物位于 `frontend/dist/build/mp-weixin`。小程序的 AppID 已写在 `src/manifest.json`；更换主体时从项目根目录执行 `node scripts/configure-miniapp.mjs 新AppID`，再重新构建。正式上传前还需在微信后台配置合法 request 域名和云函数，检查隐私设置及微信审核要求。AppSecret 只能放在后端私有环境，不得写入前端。

## 公网部署与更新

当前管理平台网址是 https://api.yjr-adc-demo.xyz/。新服务器部署时配置真实域名、HTTPS、数据库持久卷、备份及 `.env`，再通过 Docker Compose 启动；正式数据库不得使用教学密码。现有云端更新应先备份并核对运行版本，保留持久卷，确认环境变量和数据库迁移后再替换镜像。不要直接用此仓库的空白 `.env.example` 覆盖线上配置。

代码仓库包含源码和配置模板，不包含已编译的小程序包、生产数据库或云端凭据。推送 GitHub 不会自动替换微信正式版；小程序仍需通过微信开发者工具上传、审核和发布。
