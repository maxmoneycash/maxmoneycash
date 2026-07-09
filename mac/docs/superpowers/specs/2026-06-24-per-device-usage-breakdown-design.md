# 设计文档：仪表盘按设备区分用量（时间 × 设备 交叉筛选）

- 日期：2026-06-24
- 状态：待评审
- 范围：`dashboard/`（前端）+ `dashboard/edge-patches/`（云端 edge functions）

## 1. 背景与问题

用户在多台设备（例如 MacBook、Mac mini、Windows PC）上都安装了 Token Tracker 并登录了**同一账户**，开启云端同步后，所有设备的用量数据都汇聚到账户视图。当前账户视图把所有设备的数据**加总**展示，用户无法区分「哪台设备用了多少」。

本 feature 让用户在仪表盘中按设备区分用量，并能与现有的时间维度**交叉筛选**（例如「本月 × MacBook」）。

## 2. 关键现状（已核实）

这些发现决定了本设计是「暴露已有维度」而非「新建数据管线」，工作量因此大幅降低：

1. **设备数据已存在云端**：`tokentracker_devices` 表存有 `id`(device_id, UUID) / `user_id` / `device_name` / `platform` / `machine_id` / `revoked_at` / `created_at`（见 `tokentracker-device-token-issue.ts:167-281`）。设备显示名（`device_name`）现成可用。
2. **用量已按设备分别存储**：`tokentracker_hourly` 表主键为 `(user_id, device_id, hour_start, source, model)`（见 `tokentracker-ingest.ts` 的 `onConflict`）。
3. **聚合 RPC 已支持按设备子集过滤，无需改数据库**：所有 6 个 `account-*` 端点都调用同一个 RPC `account_usage_grouped(p_user_id, p_device_ids, p_from, p_to, p_trunc, p_tz, p_offset_min)`（见 `tokentracker-account-daily.ts:353-361`）。当前传入的 `p_device_ids` 是「该用户全部活跃设备」（`fetchActiveDeviceIds`，`account-daily.ts:95-107`）。**只要把它收窄为被选中的那一台，RPC 就只聚合那台设备的数据**——不需要写新 RPC、不需要数据库迁移。
4. **前端参数有统一入口**：`dashboard/src/lib/api.ts` 的 `buildFilterParams({ source, model })`（`api.ts:115-122`）是所有 usage/account fetcher 构造过滤参数的统一函数。新增 `device` 维度从这里接入。
5. **账户视图判定集中**：`AccountViewContext`（`AccountViewContext.jsx:68-72`）暴露 `accountView` 布尔值。设备筛选 UI 仅在 `accountView === true` 时出现。
6. **前端在 cloud 模式下直连 InsForge**：account view 的 hooks 走 `fetchCloudUsage*` → `fetchAccountFunction` → 直连 `getInsforgeRemoteUrl()`（`api.ts:547-587`），**不经过本地 CLI 代理**。因此本 feature 不涉及 `src/`（CLI）改动。

## 3. 目标与非目标

### 目标
- 账户视图下，仪表盘可在「全部设备」与任一台具体设备之间切换，整页数据随之过滤。
- 新增一张「按设备」占比卡片，一眼对比各设备用量占比，点击某台即筛选（与顶部下拉联动）。
- 设备维度与现有时间维度（日 / 周 / 月 / 总计 / 自定义）正交，可任意组合。

### 非目标（YAGNI，本期不做）
- 设备重命名 / 撤销设备 / 设备管理页（`device_name` 直接展示）。
- 未登录的本地视图区分设备（本地只读本机 `queue.jsonl`，本就只有一台）。
- macOS 原生 popover / `src/lib/cloud-account.js` 的跨设备代理透传 device 维度（后续可扩展，本期仅 dashboard）。
- 修改 `queue.jsonl` schema 或本地 CLI 的解析/同步逻辑。

## 4. 用户体验

仅在**登录 + 账户视图**（`accountView === true`）下出现以下两处入口，二者联动同一个 `selectedDevice` 状态：

```
右列顶部：
[日][周][月][总计][自定义]            [设备 ▾][分享][↻]
                                       └ 全部设备 / MacBook Pro / Mac mini / …

左列新增一张卡片（沿用模型/provider 占比卡样式）：
┌────────────────────────────┐
│ 按设备                       │
│ 💻 MacBook Pro       62.3%   │  ← 点击即筛选；选中态高亮
│ 🖥  Mac mini          30.1%   │
│ 🪟 Windows PC          7.6%   │
└────────────────────────────┘
```

- 默认 `selectedDevice = 全部设备`，行为与现状完全一致（不改变现有用户的体验）。
- 占比卡片的百分比按**当前选中的时间范围**计算（与时间维度交叉一致）。
- 设备图标按 `platform` 映射（darwin → Apple、win32 → Windows、linux → Linux），复用现有 `ProviderIcon` 的图标方案。
- 本地视图（未登录或未开云端同步）下两处入口都不渲染。

## 5. 架构与数据流

```
[设备下拉 / 设备卡片点击] → selectedDevice 状态 (DashboardPage)
        │
        ├─ 透传 deviceId 给所有 account 数据 hooks
        │      └─ api.ts buildFilterParams({ source, model, device }) → ?device_id=<uuid>
        │             └─ 6 个 tokentracker-account-* 端点
        │                    └─ 命中则 activeDeviceIds = [device_id]，传给现有 RPC
        │
        └─ useAccountDevices() → 新增 tokentracker-account-devices 端点
               └─ 返回设备列表 + 各设备在 [from,to] 内的总量（供下拉 + 占比卡）
```

## 6. 详细设计

### 6.1 云端：6 个 account-* 端点增加 `device_id` 过滤

对 `tokentracker-account-{summary,daily,hourly,monthly,heatmap,model-breakdown}.ts` 各做同一处小改：

1. 读取查询参数：`const deviceId = url.searchParams.get("device_id");`
2. 在已取得 `activeDeviceIds`（`fetchActiveDeviceIds(client, userId)`）之后，收窄：
   ```ts
   let scopedDeviceIds = activeDeviceIds;
   if (deviceId && activeDeviceIds.includes(deviceId)) {
     scopedDeviceIds = [deviceId];
   }
   // device_id 不属于当前用户的活跃设备 → 忽略，按全部聚合（不报错）
   ```
3. 把 `scopedDeviceIds` 传给 `account_usage_grouped` 的 `p_device_ids`。

**安全（重要）**：必须用 `activeDeviceIds.includes(deviceId)` 做归属校验——`activeDeviceIds` 来自 `fetchActiveDeviceIds(client, userId)`，已按 JWT 验证出的 `userId` 过滤。取交集可防止越权查看他人设备的数据。不在列表内的 device_id 一律忽略并回退「全部」。

**不触碰**：这些端点中的 `MODEL_PRICING` / `getModelPricing` / `computeRowCost` 区块**不修改**，因此 `test/edge-pricing-parity.test.js` 不受影响，pricing block 字节一致性保持原样。

### 6.2 云端：新增 `tokentracker-account-devices` 端点

- 鉴权：复用现有 `verifiedUserIdFromJwt`（HS256 + `JWT_SECRET`）取得 `userId`，无效则 401。
- 查询 `tokentracker_devices`（`user_id = userId AND revoked_at IS NULL`），取 `id, device_name, platform, machine_id, created_at`。
- 接收 `from` / `to` / `tz` / `tz_offset_minutes` 参数，对每台设备调用现有 `account_usage_grouped(p_device_ids=[id], p_trunc="none", …)` 求该时间范围内的 `total_tokens`，用于占比卡片与下拉排序。
  - 设备数通常很少（2–5），循环 N 次 RPC 可接受，避免改数据库。
  - 注：若后续设备数显著增多，可优化为单次「按 device 分组」的 RPC（标记为未来扩展，本期不做）。
- 响应：
  ```json
  {
    "from": "2026-06-01", "to": "2026-06-30",
    "devices": [
      { "id": "<uuid>", "device_name": "MacBook Pro", "platform": "darwin",
        "machine_id": "<hash>", "created_at": "…", "total_tokens": 882345678 }
    ]
  }
  ```
- 部署后需把该 slug 接入 InsForge edge functions 列表。

### 6.3 前端：参数透传

- `api.ts` `buildFilterParams`（`api.ts:115-122`）增加 `device` 入参：
  ```ts
  function buildFilterParams({ source, model, device }: AnyRecord = {}) {
    const params: AnyRecord = {};
    // …existing source/model…
    const normalizedDevice = typeof device === "string" ? device.trim() : "";
    if (normalizedDevice) params.device_id = normalizedDevice;
    return params;
  }
  ```
- 6 个云端 fetcher（`fetchCloudUsageSummary/Daily/Hourly/Monthly/Heatmap/ModelBreakdown`）的入参解构里加 `device`，并传给 `buildFilterParams`。本地 `getUsage*` fetcher 可一并支持（本机 queue 端点会忽略未知参数，无害），但 hook 在本地视图下不会传 `device`。
- 新增 `fetchAccountDevices({ from, to, timeZone, tzOffsetMinutes, accessToken })` → `fetchAccountFunction("tokentracker-account-devices", …)`。

### 6.4 前端：hooks

- `useUsageData`（`use-usage-data.ts`）：
  - 入参增加 `deviceId`。
  - 传给 `dailyFetcher` / `summaryFetcher`（`use-usage-data.ts:126-142` 当前未传过滤参数，需补 `device: deviceId`）。
  - **`storageKey` 必须加入 `deviceId`**（`use-usage-data.ts:42-48`）——否则切换设备会命中错误缓存。
  - 把 `deviceId` 加入 `refresh` 的依赖数组（`use-usage-data.ts:246-266`）与挂载 effect 的依赖。
- 其余账户数据 hooks（model-breakdown / trend / heatmap / 等）同样接收并透传 `deviceId`，且各自的 cacheKey 纳入 `deviceId`。
- 新增 `useAccountDevices()`：仅在 `accountView` 下拉取设备列表，随 `from/to`（及 `revision`）刷新；返回 `{ devices, loading, error }`。

### 6.5 前端：DashboardPage 与组件

- `DashboardPage.jsx` 新增 `selectedDevice` 状态（默认 `null` = 全部设备），透传 `deviceId` 给上述 hooks，并纳入各 hook 的 `cacheKey`。
- 顶部设备下拉：复用现有 `Select` 组件（`dashboard/src/ui/components/Select.jsx`），置于时间 tabs 行的右侧、`分享`/`刷新` 之前。仅 `accountView` 渲染。
- 「按设备」占比卡片：新增组件，置于左列卡片流中，沿用现有 provider/模型占比列表卡的视觉样式（参考 `DashboardView.jsx` 的 Fleet / 模型排名卡）。数据来自 `useAccountDevices()`；点击某行设置 `selectedDevice`，并与下拉共享选中态。
- **边界**：当设备列表刷新后 `selectedDevice` 指向的设备已不存在（被 revoke），自动回退到「全部设备」。

### 6.6 文案

- `dashboard/src/content/copy.csv` 新增设备筛选相关 key（标签「按设备 / 全部设备 / 设备」等），不得硬编码。
- 同步检查 `dashboard/src/content/i18n/*/dashboard.json` 是否需要补翻译。
- 通过 `npm run validate:copy` 与 `npm run validate:ui-hardcode`。

## 7. 数据契约

- 请求：账户数据端点接受可选查询参数 `device_id=<uuid>`；缺省或非法值 → 等同「全部设备」。
- `tokentracker-account-devices` 响应见 6.2。
- 设备显示名 = `device_name`（必要时附 `platform`，如「MacBook Pro · darwin」）。

## 8. 测试计划

- 云端端点单测/契约测试：device_id 命中 → 仅该设备数据；非法 device_id → 回退全部；越权 device_id（他人设备）→ 不泄漏（被 `includes` 过滤）。
- `account-devices` 端点：返回字段完整、`total_tokens` 与逐设备聚合一致、随 from/to 变化。
- 前端：`buildFilterParams` 透传 `device_id`；`useUsageData` 的 `storageKey` 随 `deviceId` 变化（防缓存串台）；本地视图不渲染设备入口。
- 回归：默认「全部设备」时各端点与现状字节一致（不改变既有用户体验）。
- `npm test`、`npm run validate:copy`、`npm run validate:ui-hardcode`、`npm run validate:guardrails`。

## 9. 部署

- 部署改动过的 6 个 `account-*` 端点 + 新增的 `account-devices` 端点到 InsForge。
- 前端随 `src/`/`dashboard/` 发布流程走（按 CLAUDE.md：dashboard 改动需 npm + DMG + Windows 三端同发）。本设计**不改 `src/`**，但改了 `dashboard/`，因此仍属「dashboard 改动」发布范畴。

## 10. 风险与权衡

- **N 次 RPC 求各设备总量**：设备数小，开销可接受；大量设备时再优化为分组 RPC。
- **缓存串台**：必须把 `deviceId` 纳入所有相关 hook 的 `storageKey`，否则切设备显示旧数据。
- **越权风险**：device_id 必须经 `activeDeviceIds.includes()` 校验，已在设计中固化。
- **空状态**：账户仅 1 台设备时，占比卡片只有一行（100%），下拉仍可用但意义有限——可考虑设备数 ≤1 时隐藏占比卡片（实现阶段决定）。

## 11. 未来扩展（非本期）

- 标记「本机」：localhost 下本地 server 知道 `machine_id`（`getOrCreateMachineId`），可比对设备列表高亮当前设备。
- 设备重命名 / 撤销。
- macOS 原生 popover 跨设备视图按设备筛选（`src/lib/cloud-account.js` 透传）。
- 单次「按 device 分组」RPC 优化。

## 12. 待评审者确认的默认决策

以下点我已设合理默认，请评审时留意是否调整：
1. 占比卡片百分比按**当前时间范围**计算（而非全时间）。
2. 设备显示名直接用 `device_name`（必要时拼 `platform`），不提供重命名。
3. 「标记本机」列为未来扩展，本期不做。
4. 账户仅 1 台设备时，占比卡片是否隐藏（倾向隐藏）——实现阶段定。
