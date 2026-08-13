import { createApp } from 'vue/dist/vue.esm-bundler.js';
import App, { setupApp } from './app.js';
import FilterSelect from './components/FilterSelect.vue';

const app = createApp(App);
app.component('filter-select', FilterSelect);
setupApp(app);
const instance = app.mount('#app');
// 暴露实例便于调试与自动化测试
window.__QAS_APP__ = instance;
