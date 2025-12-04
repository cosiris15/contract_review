import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import { clerkPlugin } from '@clerk/vue'
import { zhCN } from '@clerk/localizations'

import App from './App.vue'
import router from './router'

// 只导入实际使用的图标
import {
  ArrowDown, ArrowLeft, ArrowRight, Briefcase, ChatDotRound,
  ChatDotSquare, ChatLineSquare, Check, CircleCheck, CircleCheckFilled,
  CircleClose, CirclePlus, Clock, Close, Coin, Collection, CopyDocument,
  Cpu, Delete, Document, DocumentChecked, Download, Edit, EditPen,
  Files, Folder, FolderOpened, HomeFilled, InfoFilled, List, Loading,
  MagicStick, Plus, Promotion, Refresh, Remove, Right, Search, Setting,
  SortDown, SortUp, Tools, Upload, UploadFilled, User, View, Warning
} from '@element-plus/icons-vue'

const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

if (!PUBLISHABLE_KEY) {
  throw new Error('Missing Clerk Publishable Key. Add VITE_CLERK_PUBLISHABLE_KEY to .env.local')
}

const app = createApp(App)

// 只注册使用到的图标
const icons = {
  ArrowDown, ArrowLeft, ArrowRight, Briefcase, ChatDotRound,
  ChatDotSquare, ChatLineSquare, Check, CircleCheck, CircleCheckFilled,
  CircleClose, CirclePlus, Clock, Close, Coin, Collection, CopyDocument,
  Cpu, Delete, Document, DocumentChecked, Download, Edit, EditPen,
  Files, Folder, FolderOpened, HomeFilled, InfoFilled, List, Loading,
  MagicStick, Plus, Promotion, Refresh, Remove, Right, Search, Setting,
  SortDown, SortUp, Tools, Upload, UploadFilled, User, View, Warning
}
for (const [key, component] of Object.entries(icons)) {
  app.component(key, component)
}

app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })
app.use(clerkPlugin, {
  publishableKey: PUBLISHABLE_KEY,
  localization: zhCN
})

app.mount('#app')
