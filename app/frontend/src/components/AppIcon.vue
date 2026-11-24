<script setup lang="ts">
import UniIcons from '@dcloudio/uni-ui/lib/uni-icons/uni-icons.vue'
withDefaults(defineProps<{name:string;size?:number;color?:string}>(),{size:22,color:'#3278cf'})
</script>
<template><UniIcons :type="name" :size="size" :color="color"/></template>
