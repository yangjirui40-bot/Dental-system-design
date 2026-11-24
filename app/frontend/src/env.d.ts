/// <reference types="vite/client" />
declare module '*.vue' { import { DefineComponent } from 'vue'; const c: DefineComponent<any, any, any>; export default c }
