import fs from 'node:fs'
const appid=process.argv[2]
if(!/^wx[a-f\d]{16}$/i.test(appid||''))throw new Error('请提供微信公众平台的小程序AppID，例如wx后跟16位标识；不要提供AppSecret')
const file=new URL('../frontend/src/manifest.json',import.meta.url)
const manifest=JSON.parse(fs.readFileSync(file,'utf8'));manifest['mp-weixin'].appid=appid
fs.writeFileSync(file,JSON.stringify(manifest,null,2)+'\n');console.log('小程序AppID已写入manifest.json')
