<script>
// 统一筛选下拉组件（Vue 3 SFC）
// 单层玻璃胶囊：标签与当前值同行垂直居中，自定义箭头，无原生 select 外观
// type: 'select'（默认）| 'input'（文本输入模式，无下拉箭头）
export default {
  name: 'FilterSelect',
  props: {
    modelValue: { default: '' },
    label: { type: String, default: '' },
    options: { type: Array, default: () => [] }, // [{value, text}] 或 ['a','b']
    placeholder: { type: String, default: '' },
    clearable: { type: Boolean, default: false },
    title: { type: String, default: '' },
    type: { type: String, default: 'select' }
  },
  emits: ['update:modelValue', 'change'],
  computed: {
    hasValue() {
      return this.modelValue !== '' && this.modelValue !== null && this.modelValue !== undefined;
    }
  },
  methods: {
    clearValue() {
      this.$emit('update:modelValue', '');
    },
    // 原生 select 的值总是字符串，这里按 options 还原原始类型（布尔/数字），并透传 change 事件
    onChange($event) {
      const raw = $event.target.value;
      let matched = raw;
      const found = this.options.find(o => {
        const v = o && o.value !== undefined ? o.value : o;
        return String(v) === raw;
      });
      if (found !== undefined) {
        matched = found && found.value !== undefined ? found.value : found;
      }
      this.$emit('update:modelValue', matched);
      this.$emit('change', matched);
    },
    // 文本输入模式：透传 change 事件
    onInput($event) {
      this.$emit('update:modelValue', $event.target.value);
      this.$emit('change', $event.target.value);
    }
  }
};
</script>

<template>
  <div class="filter-select" :title="title">
    <span class="filter-select-label" v-if="label">{{ label }}</span>
    <div class="filter-select-field">
      <select v-if="type !== 'input'" class="filter-select-native" :value="modelValue" @change="onChange">
        <option v-if="placeholder" value="">{{ placeholder }}</option>
        <option v-for="opt in options" :key="opt && opt.value !== undefined ? opt.value : opt"
                :value="opt && opt.value !== undefined ? opt.value : opt"
                v-html="opt && opt.text !== undefined ? opt.text : opt"></option>
      </select>
      <input v-else type="text" class="filter-select-native filter-select-input"
             :value="modelValue" @input="onInput" :placeholder="placeholder">
      <i v-if="type !== 'input'" class="bi bi-chevron-down filter-select-arrow"></i>
    </div>
    <button type="button" class="filter-select-clear" v-if="clearable && hasValue" @click="clearValue" title="清除筛选">
      <i class="bi bi-x-lg"></i>
    </button>
  </div>
</template>
