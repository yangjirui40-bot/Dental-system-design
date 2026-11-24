import { defineConfig,loadEnv,type Plugin } from 'vite'
import uni from '@dcloudio/vite-plugin-uni'
const plugin=typeof uni==='function'?uni:(uni as any).default
// The pinned uni-h5 Picker reuses three unkeyed DIV branches when desktop
// native dates switch to mobile popups. Give each branch a stable identity so
// Vue preserves the popup container classes. Only H5 is transformed; neither
// node_modules nor the WeChat build is changed. Fail closed after an upgrade.
function stablePickerBranches():Plugin{
 let transformed=false
 return {name:'adc-stable-picker-branches',enforce:'pre',transform(source,id){
  if((globalThis as any).process?.env?.UNI_PLATFORM!=='h5'||!id.replace(/\\/g,'/').endsWith('/@dcloudio/uni-h5/dist/uni-h5.es.js'))return
  const patches=[
   ['"ref": pickerRef,','"key": "adc-picker-popup", "ref": pickerRef,'],
   ['createVNode("div", null, [slots.default && slots.default()]), system.value ?', 'createVNode("div", {key:"adc-picker-slot"}, [slots.default && slots.default()]), system.value ?'],
   ['"class": "uni-picker-system",','"key": "adc-picker-system", "class": "uni-picker-system",']
  ]
  for(const [before,after] of patches){if(source.split(before).length!==2)throw Error('Pinned uni-h5 picker changed; review the responsive date fix');source=source.replace(before,after)}
  transformed=true;return {code:source,map:null}
 },buildEnd(error){if(!error&&(globalThis as any).process?.env?.UNI_PLATFORM==='h5'&&!transformed)throw Error('H5 picker branch fix was not applied')}}
}
export default defineConfig(({mode})=>{
 const apiProxy=loadEnv(mode,'.','ADC_').ADC_API_PROXY||'http://127.0.0.1:8000'
 return {plugins:[stablePickerBranches(),plugin()],server:{host:'127.0.0.1',port:5173,watch:{usePolling:true,interval:750},proxy:{'/api':{target:apiProxy,changeOrigin:true},'/healthz':{target:apiProxy,changeOrigin:true}}}}
})
