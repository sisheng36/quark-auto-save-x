import { createApp } from 'vue/dist/vue.esm-bundler.js';
import App, { setupApp } from './app.js';
import FilterSelect from './components/FilterSelect.vue';

const app = createApp(App);
// 压缩模板编译产物中的空白文本节点，减少首次挂载时的 DOM 创建量
app.config.compilerOptions.whitespace = 'condense';
app.component('filter-select', FilterSelect);
setupApp(app);
const instance = app.mount('#app');
// 暴露实例便于调试与自动化测试
window.__QAS_APP__ = instance;
