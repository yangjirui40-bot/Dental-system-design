# 患者小程序云通道

1.3.0 使用微信云函数 `adcNetworkGateway`。云函数验证微信 AppID 后，经 HTTPS 调用固定的诊所 API `api.yjr-adc-demo.xyz`。它为患者请求标注 `X-ADC-Surface: patient`，并统一账号登录的客户端类型。后端继续核实会话、账号类型、门店、业务角色和患者授权。

HTTPS 实现在 `https-entry.js` 与 `https-forward.js`。新建同配置部署目录时将 `https-entry.js` 命名为 `index.js`，并随 `https-forward.js`、`policy.js`、`context.js` 发布。当前线上增量发布将两个 HTTPS 文件合为一个 `index.js`，复用函数原有的 `policy.js` 和 `context.js`。HTTPS 版本使用 Node 自带模块，应用包无需保存私钥或云运行配置。

源码中的 `index.js` 和 `tunnel.js` 保留旧版 SSH 发布实现及测试，以对应历史版本。本轮增量操作只更新现有患者网关函数代码。原公网域名和 Docker 服务继续作为管理端与微信患者服务共用的后端。

发布后通过微信官方模拟器调用健康接口。应看到 HTTP 200、原 PostgreSQL 版本和 `gatewayDiagnostics.transport` 为 `https`。再验证患者和代办账号、具体患者范围及员工账号拒绝。网络诊断只保存连接阶段和耗时。
