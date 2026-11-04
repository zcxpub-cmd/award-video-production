import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig({plugins:[react()],build:{outDir:"dist-runtime"},server:{host:'127.0.0.1',port:5176,strictPort:true,proxy:{'/api':'http://127.0.0.1:8790'}},preview:{host:'127.0.0.1',port:8790,strictPort:true}})
