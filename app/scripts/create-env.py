from pathlib import Path
import argparse,secrets,re
p=argparse.ArgumentParser();p.add_argument('--domain',default='localhost');a=p.parse_args()
if not re.fullmatch(r'[a-zA-Z0-9.-]+',a.domain):raise SystemExit('请填写纯域名，不带协议、路径或端口')
root=Path(__file__).resolve().parents[1];target=root/'.env'
if target.exists():raise SystemExit('.env已存在，请在原文件核对配置；此脚本不会覆盖密钥')
target.write_text('POSTGRES_DB=adc\nPOSTGRES_USER=adc\nPOSTGRES_PASSWORD='+secrets.token_urlsafe(36)+'\nSECRET_KEY='+secrets.token_urlsafe(64)+'\nALLOWED_HOSTS=localhost,127.0.0.1,'+a.domain+'\nCORS_ORIGINS=http://localhost:8080,http://127.0.0.1:8080,https://'+a.domain+'\nDEBUG=0\nSECURE_SSL_REDIRECT=0\nAPI_DOMAIN='+a.domain+'\n')
target.chmod(0o600);print('已生成.env，密钥未显示；该文件已被.gitignore排除')
