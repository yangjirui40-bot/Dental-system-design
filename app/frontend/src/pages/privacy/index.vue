<script setup lang="ts">
import AppIcon from '../../components/AppIcon.vue'
function back(){if(getCurrentPages().length>1)uni.navigateBack();else uni.reLaunch({url:'/pages/index/index'})}
const sections=[{title:'适用范围',text:'本说明适用于“问解连锁作业”小程序及其配套ADC牙科诊所教学演示。当前业务与临床资料使用合成内容，不提供真实医疗服务；微信登录标识摘要、必要账号及运行日志按真实使用处理。请勿输入真实患者病历、证件或他人的个人信息。'},
{title:'账号与业务资料',text:'系统处理独立账号、口令散列、会话凭据，以及在表单中输入的姓名、出生日期、联系方式、联系人和代办关系。过敏、诊疗、治疗计划及结算资料用于教学流程演示，当前只允许合成内容。按本人、逐患者授权和员工岗位、门店范围访问。退出时移除客户端登录凭据。'},
{title:'运行记录与设备布局',text:'系统记录必要的操作账号、时点、业务编号及摘要，访问日志包含IP、请求路径与响应状态。审计不记录口令或复制病历正文，生产代理不记录搜索查询串。微信状态栏、窗口和胶囊尺寸只在客户端用于界面布局，不用于广告分析。'},
{title:'平台接口与组件',text:'本程序支持独立账号与可选微信登录。微信临时凭证仅由后端验证，保存AppID、微信标识的摘要与已核实业务账号的绑定，用于登录、选择已有授权身份及找回密码；不保存或下发微信会话密钥。不接入微信头像昵称、手机号授权、定位、相机、通讯录、支付或广告接口。客户端使用Vue、uni-app和微信基础库，未启用DCloud统计。后台使用Django、PostgreSQL和Nginx，阿里云提供服务器基础设施。'},
{title:'微信开发体验连接',text:'开发体验版使用腾讯微信云开发传递接口请求。登录表单、会话凭据和操作数据经微信云函数，通过加密连接转交原阿里云后端；业务数据仍保存在原数据库，不另建云开发业务数据库。云函数代码不输出请求正文、口令或凭据，平台可能处理调用及运行所需日志，适用腾讯云相关说明。正式发布连接以实际备案及平台审核结果为准。'},
{title:'保存、备份与处理',text:'演示服务位于阿里云中国北京，数据库使用受控持久卷；备份保存在服务器及项目负责人电脑。备份、环境密钥、口令和私钥不收入公开源码包。当前没有固定天数自动删除或自助注销全部历史的功能；业务签署和修订链保留完整性，负责人核查有效请求后处理。'},
{title:'你的请求与联系',text:'查询、更正、停止使用、误录信息处理或安全问题，请联系2684077388@qq.com，说明涉及账号、业务编号与请求事项。不要在首封邮件发送口令、身份证照片或完整病历。负责人核对账号关系后说明处理结果及必要限制。'},
{title:'未成年人及用途变化',text:'当前不接受真实未成年人健康资料。若误录真实或未成年人资料，请停止继续输入并联系负责人。未来用途或信息处理变化时，应同步更新说明并按实际要求办理相应告知、同意及平台手续。'}]
let top=0
// #ifdef MP-WEIXIN
top=uni.getSystemInfoSync().statusBarHeight||0
// #endif
</script>
<template><view class="privacy-page"><view class="privacy-topbar" :style="{paddingTop:top+'px'}"><button aria-label="返回" @click="back"><AppIcon name="left" color="#253347"/></button><text>隐私说明</text></view><view class="privacy-content"><text class="privacy-title">问解连锁作业隐私说明</text><text class="privacy-date">版本日期：2026年11月14日</text><view v-for="section in sections" :key="section.title" class="privacy-section"><text>{{section.title}}</text><text>{{section.text}}</text></view><view class="contact"><AppIcon name="email" :size="20"/><text>2684077388@qq.com</text></view></view></view></template>
<style scoped>.privacy-topbar{background:#fff;min-height:64px;border-bottom:1px solid #e3e8ef;display:flex;align-items:center;gap:10px;padding:10px 20px;font-size:18px;font-weight:600}.privacy-topbar button{border:0;background:transparent;padding:10px;min-width:44px}.privacy-content{max-width:820px;margin:28px auto;padding:32px;background:#fff;border:1px solid #e3e8ef;border-radius:12px}.privacy-title{display:block;font-size:25px;font-weight:600;line-height:1.5}.privacy-date{display:block;color:#758296;font-size:12px;margin-top:10px}.privacy-section{margin-top:28px}.privacy-section>text:first-child{display:block;font-size:17px;font-weight:600;margin-bottom:10px}.privacy-section>text:last-child{font-size:14px;line-height:2;color:#253347;display:block}.contact{display:flex;align-items:center;gap:10px;border-top:1px solid #e3e8ef;padding-top:22px;margin-top:30px;font-size:14px;color:#3278cf}@media(max-width:680px){.privacy-content{margin:18px;padding:23px 20px}.privacy-title{font-size:21px}.privacy-section>text:first-child{font-size:16px}.privacy-section>text:last-child{font-size:13px;line-height:1.95}.privacy-topbar{padding-left:6px}.contact{font-size:13px}}</style>
