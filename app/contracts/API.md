# 接口与联调约定

根地址本地为`http://localhost:8000`，生产为部署后的实际HTTPS域名。H5经Vite/Nginx同源代理；微信端`VITE_API_BASE`填写根地址，不额外拼`/api`。

## 登录与查询

|方法|路径|用途|
|---|---|---|
|POST|`/api/auth/login`|`login_name`、`password`，返回token和授权岗位；失败不披露他人身份|
|POST|`/api/auth/scope`|`scope_id`切换已有有效授权，返回新token|
|GET|`/api/workspace`|当前身份、范围、用例菜单、经授权的资源摘要|
|GET|`/api/slots`|patient_id、clinic_id、date、standard_ids（逗号分隔）、minutes、presenting_request及可选phase_id，返回完整可约时段|
|GET|`/api/records`|resource为patients/appointments/invoices，q为搜索词、before为上一页末项id；按当前权限查询|
|GET|`/api/encounters/{id}`|有权牙医读取临床草稿、既有签署与本次阶段|
|GET|`/api/plans/{id}`|有权牙医加载实际方案、阶段、依赖及版本|
|GET|`/api/invoices/{id}`|读取有权访问的实际结算明细|
|GET|`/api/reports`|quarter_id，按集团或主管门店范围分析|
|GET|`/api/audit`|有权岗位读取范围内业务操作记录|
|GET|`/healthz`|数据库连通性与版本|

登录后发送`Authorization: Bearer 返回的token`，登录凭据最长8小时有效；密码改变、账号停用和岗位撤销均在后续请求重新核验。不要把token打印到公开日志。

## 用例命令

写入用例命令采用`POST /api/use-cases/{UC编号}`；UC14、UC17通过下表的GET查询接口办理，不接受伪造的写入命令。请求JSON包含`action`和对应业务字段；准确字段及类型见`frontend/src/forms.ts`，完整行为见同目录`design.json`。这不是任意表CRUD接口。

|用例|支持的动作|
|---|---|
|UC01|save、contact、allergy、authority、revoke-authority|
|UC02|book|
|UC03|cancel、reschedule、contact|
|UC04|arrive、start、leave、no_show、correct|
|UC05|draft、sign|
|UC06|issue、correct、approve-price|
|UC07|save、manager|
|UC08|employee、dentist、qualification-kind、qualification、revoke|
|UC09|publish、replace、stop、travel-rule|
|UC10|catalog、draft、approve、disable|
|UC11|source、review、submission、review-submission|
|UC12|analyze、confirm|
|UC13|draft、confirm、phase|
|UC14|GET /api/workspace、/api/records及有权结算明细|
|UC15|calendar、operatory|
|UC16|create、grant、revoke、password、disable、enable|
|UC17|GET /api/audit（审计读取）|

每次业务写入发送`Idempotency-Key: UUID`。相同账号/范围、路径、内容和凭据只提交一次，重试反馈原引用`id`和`replayed: true`；改变内容须使用新UUID。修改已有对象时提交读取的`row_version`，不可猜测版本。日期为ISO年月日，时间为带时区的ISO时间，金额/数量按字段精度填写；确认字段是真正JSON布尔值，不是字符串`"false"`。

预约命令携带服务端候选的doctor/duty/operatory/time对应字段（源码字段为`dentist_id`、`duty_id`、`operatory_id`、`starts_at`、`ends_at`），再带实际患者、拟项目、诉求和可选阶段。候选不是资源锁，保存时会重新核验。不能由客户端指定经办职员或批准人。

## 原设计第4.2节具体操作地址

以下入口与统一用例入口共用服务、权限、事务及请求凭据：

|POST路径|责任|
|---|---|
|`/api/appointments`|UC02预约|
|`/api/appointments/{no}/reschedule`|UC03改期|
|`/api/duties/{no}/replace`|UC09/UC03替班|
|`/api/duties/{no}/stop`|UC09/UC03机构停诊|
|`/api/encounters/{no}/sign`|UC05/UC06/UC13签署协作|
|`/api/encounters/{no}/invoice`|UC06补结算|
|`/api/invoices/{no}/revisions`|UC06批准结算修订|
|`/api/plans/{no}/revisions/{version}/confirm`|UC13确认已经保存的该修订，不另造下一个版本|
|`/api/cost-sources/{no}/revisions/{version}/review`|UC11指定allocation_ids复核，不能混入其他来源/修订的分摊|
|`/api/quarters/{YYYY-Qn}/reports/confirm`|UC12正式确认季度报告|

编号位置可使用内部数值id；支持文本业务编号的对象也可用其业务编号。凭据存在多行来源且文本编号不能唯一定位时会拒绝，必须选择明确记录id，不默认取第一行。

## 错误

错误JSON为`error`和可显示的`message`。400为格式/缺请求凭据，401为登录失效，403为岗位/范围不允许，404为不存在，409为版本、占用或并发冲突，422为具体业务条件未满足。网络中断无法确定结果时保留同一凭据重试，不向用户假报成功；临床签署后的`billing_state`须分别说明已开票或待处理。

## 1.2.0认证补充

新增接口、输入、有效期及访问边界见[补充规约](../specs/003-account-access/spec.md)。原业务接口保留。微信code由服务器验证，前端不可用自填openid登录；有效身份取自原账号和当前授权。微信会话与密码会话分开签名，解绑及重设密码会撤销相应会话。原UC16新增unbind-wechat动作，必须有原权限与明确身份核实依据。

1.2.1补充：完全相同姓名（按数据库大小写规则）、出生日期和电话原值的自助注册，在事务内串行核查。先前请求未提交时后请求等待，再返回原有409重复资料结果；不生成重复患者，不合并或接管既有档案。原接口字段与业务表结构不变。
