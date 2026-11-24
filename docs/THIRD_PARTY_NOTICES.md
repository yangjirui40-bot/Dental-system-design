# 第三方来源说明

- `.specify/templates/spec-template.md`来自[GitHub Spec Kit官方模板](https://github.com/github/spec-kit/blob/main/templates/spec-template.md)，许可保留于[contracts/SPEC_KIT_LICENSE](contracts/SPEC_KIT_LICENSE)。本项目使用其规约组织方式，本次未执行Spec Kit CLI。
- 前端依赖基于[uni-preset-vue官方vite-ts模板](https://github.com/dcloudio/uni-preset-vue/tree/vite-ts)的包清单，实际版本锁定于`frontend/package-lock.json`；相关软件的许可证以各依赖自身发布为准。
- Vue、Django、PostgreSQL、psycopg、Gunicorn、Nginx、Caddy和Docker均为各自项目，保留其名称以说明技术选型，不主张这些软件由本项目原创。
- 原业务规约、SQL和原型来自用户指定的课程设计文件。外部产品研究仅用于检视流程；没有使用参考产品的Logo、宣传图片、真实患者或第三方品牌文案。
- 交付中的人名、地址、账号和病例为教学/测试合成资料，不代表真实诊所数据；正式初始化要求操作者填写两个实际责任人的资料。
- `tools/wechat-automation`使用微信官方`miniprogram-automator`0.13.0（MIT许可）连接本机开发者工具，只用于测试，不随客户端作为业务SDK运行。依赖版本见该目录package-lock.json。
