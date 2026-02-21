# UI增强功能实施计划

> 计划制定时间：2026-01-04
> 预计实施时长：3-4小时

---

## 目标概述

增强交互式审阅界面的用户体验，提供更直观的文档变更可视化和管理功能。

---

## 现有实现分析

### DiffView.vue（已有基础）
**当前功能**：
- ✅ 字符级别的diff显示（使用 `diffChars`）
- ✅ 高亮显示新增/删除内容
- ✅ 基本的样式和图例

**限制**：
- ❌ 仅支持内联视图，没有并排对比
- ❌ 没有与document store集成
- ❌ 缺少操作按钮（应用/撤销变更）
- ❌ 没有变更统计信息

### DocumentViewer.vue（已有基础）
**当前功能**：
- ✅ 段落列表展示
- ✅ 基于highlightText的段落高亮
- ✅ 自动滚动到高亮段落
- ✅ 脉冲动画效果

**限制**：
- ❌ 没有显示AI修改过的段落
- ❌ 没有段落级别的变更标记
- ❌ 无法查看段落的变更历史
- ❌ 没有与document store集成

---

## 实施任务分解

### Task 1：DiffView.vue - 添加并排对比视图（Split View）

**预计时间**：1小时

**功能描述**：
- 提供"内联视图"和"并排视图"两种模式切换
- 并排视图：左侧显示original，右侧显示modified
- 使用 `diffLines` 进行行级别的diff

**实施步骤**：
1. 添加视图模式切换按钮（inline/split）
2. 实现split视图布局（两列）
3. 扩展diff计算逻辑支持 `diffLines`
4. 添加行号显示
5. 同步滚动功能

**涉及文件**：
- `frontend/src/components/interactive/DiffView.vue`

**代码估计**：+150行

---

### Task 2：DiffView.vue - 集成document store和操作按钮

**预计时间**：45分钟

**功能描述**：
- 从document store读取变更数据
- 添加"应用变更"和"撤销变更"按钮
- 显示变更的状态（pending/applied/reverted）

**实施步骤**：
1. 导入 `useDocumentStore`
2. 接收 `changeId` prop（指定要显示的变更）
3. 从store获取变更的original和modified内容
4. 添加操作按钮（Apply Change / Revert Change）
5. 调用 `documentStore.applyChange()` 和 `documentStore.revertChange()`
6. 显示操作状态和结果提示

**涉及文件**：
- `frontend/src/components/interactive/DiffView.vue`
- `frontend/src/store/document.js`（可能需要微调）

**代码估计**：+80行

---

### Task 3：DiffView.vue - 添加变更统计和元数据

**预计时间**：30分钟

**功能描述**：
- 显示变更统计：+X行，-Y行，~Z处修改
- 显示变更元数据：工具名称、执行时间、状态

**实施步骤**：
1. 计算diff统计信息（additions, deletions, modifications）
2. 添加元数据展示区域
3. 美化样式

**涉及文件**：
- `frontend/src/components/interactive/DiffView.vue`

**代码估计**：+60行

---

### Task 4：DocumentViewer.vue - 集成document store显示段落修改状态

**预计时间**：1小时

**功能描述**：
- 从document store获取所有变更
- 标记被AI修改过的段落
- 显示段落的变更状态（pending/applied/reverted）
- 使用不同颜色区分状态

**实施步骤**：
1. 导入 `useDocumentStore`
2. 创建 `paragraphChangeStatus` computed属性
   - 映射 paragraph_id → 变更状态
3. 扩展段落CSS类：`modified-pending`, `modified-applied`, `modified-reverted`
4. 在段落上添加状态徽章（badge）
5. 添加图例说明

**涉及文件**：
- `frontend/src/components/interactive/DocumentViewer.vue`
- `frontend/src/store/document.js`

**代码估计**：+100行

---

### Task 5：DocumentViewer.vue - 添加段落点击查看变更历史

**预计时间**：45分钟

**功能描述**：
- 点击段落可查看该段落的所有变更记录
- 使用Popover或Dialog显示变更历史
- 支持查看每个变更的详细diff

**实施步骤**：
1. 添加段落点击事件处理
2. 创建变更历史查看组件（可复用DiffView）
3. 从document store获取段落的所有变更
4. 使用 `el-popover` 或 `el-drawer` 展示
5. 显示变更时间线

**涉及文件**：
- `frontend/src/components/interactive/DocumentViewer.vue`
- 可能新增：`frontend/src/components/interactive/ChangeHistoryPopover.vue`

**代码估计**：+120行

---

## 实施优先级

### 阶段一：核心可视化（Task 1 + Task 4） - 2小时
**优先级：高**
- Task 1：DiffView并排对比视图
- Task 4：DocumentViewer段落修改状态标记

**理由**：这两个任务提供最直观的用户体验提升，让用户能清晰看到"哪些段落被修改了"以及"具体修改了什么"。

### 阶段二：交互增强（Task 2 + Task 5） - 1.5小时
**优先级：中**
- Task 2：DiffView操作按钮（应用/撤销）
- Task 5：DocumentViewer点击查看历史

**理由**：提供变更管理的交互能力，用户可以直接在UI上操作变更。

### 阶段三：信息完善（Task 3） - 30分钟
**优先级：低**
- Task 3：DiffView统计和元数据

**理由**：锦上添花，提供更多上下文信息。

---

## 技术依赖

### NPM包
- ✅ `diff` - 已安装，用于diffChars/diffLines
- ✅ `element-plus` - 已安装，用于UI组件

### 内部依赖
- ✅ `store/document.js` - 文档变更状态管理
- ✅ document_changes表 - 后端数据支持

---

## 数据流设计

### DiffView增强数据流
```
Parent Component (e.g., ChatPanel)
    ↓ props: changeId
DiffView.vue
    ↓ useDocumentStore()
    ├── getChangeById(changeId)
    ├── original vs modified
    ├── diff calculation
    ├── user clicks "Apply"
    └── documentStore.applyChange(changeId)
         ↓ API call
         ↓ update state
         └── trigger rerender
```

### DocumentViewer增强数据流
```
InteractiveReviewView
    ↓ props: paragraphs
DocumentViewer.vue
    ↓ useDocumentStore()
    ├── allChanges
    ├── compute paragraphChangeStatus
    │    - paragraph_id → [pending|applied|reverted]
    ├── render with status badges
    └── on click paragraph
         ↓ show ChangeHistoryPopover
         └── display all changes for that paragraph
```

---

## 边界情况处理

1. **段落ID映射**
   - 问题：后端paragraph_id可能是从1开始，前端paragraphs[index]从0开始
   - 解决：在document store中规范化ID映射

2. **并发变更冲突**
   - 问题：同一段落有多个pending变更
   - 解决：按created_at排序，显示最新的变更

3. **大文档性能**
   - 问题：超长文档diff计算可能卡顿
   - 解决：保持现有的MAX_TEXT_LENGTH限制，添加虚拟滚动（可选）

4. **变更已应用后的状态同步**
   - 问题：用户apply变更后，DocumentViewer需要实时更新状态
   - 解决：利用Pinia的响应式特性，computed会自动更新

---

## 测试计划

### 手动测试场景

**DiffView测试**：
1. 切换内联/并排视图，验证布局正确
2. 显示一个modify_paragraph变更，验证diff正确
3. 点击"应用变更"，验证状态更新和API调用
4. 验证统计信息准确（+X/-Y行）

**DocumentViewer测试**：
1. AI修改3个段落，验证段落显示对应的状态徽章
2. 点击修改过的段落，验证弹出变更历史
3. Apply一个变更，验证徽章颜色变化（pending → applied）
4. Revert一个变更，验证徽章颜色变化（applied → reverted）

---

## 实施检查清单

### Task 1: Split View
- [ ] 添加视图模式切换UI
- [ ] 实现split布局（左右两列）
- [ ] 实现diffLines逻辑
- [ ] 添加行号
- [ ] 实现同步滚动
- [ ] 测试各种diff场景

### Task 2: 操作按钮
- [ ] 集成document store
- [ ] 添加Apply/Revert按钮
- [ ] 实现按钮点击逻辑
- [ ] 添加状态显示
- [ ] 添加成功/失败提示

### Task 3: 统计信息
- [ ] 计算diff统计
- [ ] 设计元数据展示UI
- [ ] 显示工具名称、时间等

### Task 4: 段落状态标记
- [ ] 集成document store
- [ ] 实现paragraphChangeStatus计算
- [ ] 添加状态徽章CSS
- [ ] 添加图例说明
- [ ] 测试状态更新响应

### Task 5: 变更历史
- [ ] 添加段落点击事件
- [ ] 创建历史查看组件
- [ ] 实现变更时间线
- [ ] 集成DiffView显示详细内容
- [ ] 测试用户交互

---

## 预期成果

### 用户体验改进
1. **直观的变更可视化**：用户可以清楚看到哪些段落被AI修改了
2. **灵活的对比模式**：内联视图快速浏览，并排视图详细对比
3. **便捷的变更管理**：点击即可应用或撤销变更，无需切换页面
4. **完整的变更历史**：每个段落的修改记录一目了然

### 技术收益
1. **充分利用document store**：前端状态管理发挥作用
2. **组件复用性提升**：DiffView可被多个场景使用
3. **与后端API完全对接**：apply/revert API得到前端入口

---

## 后续优化方向（未来）

1. **批量操作**：批量应用/撤销多个变更
2. **变更对比**：对比两个不同版本的draft
3. **导出变更报告**：生成变更摘要PDF
4. **实时协作**：多用户同时审阅时显示他人的变更
5. **撤销栈**：支持Undo/Redo操作
6. **变更注释**：为变更添加备注说明

---

**总预计时间**：3-4小时
**建议实施顺序**：Task 1 → Task 4 → Task 2 → Task 5 → Task 3
