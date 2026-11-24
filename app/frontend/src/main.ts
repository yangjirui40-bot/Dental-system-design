import { createSSRApp } from 'vue'
import App from './App.vue'
// #ifdef H5
// Load the official picker mask before a lazily loaded form can mount it.
import '@dcloudio/uni-h5/style/picker.css'
// #endif
export function createApp() { const app=createSSRApp(App);return {app} }
