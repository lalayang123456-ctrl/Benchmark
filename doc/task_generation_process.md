# VLN Benchmark 任务生成流程详细文档

本文档详细描述了 VLN Benchmark 系统中导航任务（Task）的自动生成过程。该系统能够基于指定的地理位置和 POI（兴趣点）类型，自动生成完整的街景导航任务数据。

---

## 一、整体架构概览

任务生成系统采用模块化设计，由以下核心组件协同工作：

| 模块 | 文件 | 职责 |
|------|------|------|
| **主编排器** | `task_assembler.py` | 协调各模块完成完整的任务生成流水线 |
| **POI 搜索器** | `poi_searcher.py` | 调用 Google Places API 搜索兴趣点 |
| **路线获取器** | `directions_fetcher.py` | 调用 Google Routes API 获取导航路线和指令 |
| **白名单生成器** | `whitelist_generator.py` | 通过 BFS 算法探索街景全景图网络，生成可行区域 |
| **链接增强器** | `link_enhancer.py` | 添加虚拟连接、修剪远距离链接 |
| **POI 配置** | `poi_config.json` | 定义 POI 类别及其搜索关键词 |

---

## 二、任务生成模式特性

当前系统使用 V2 模式（`generate_batch_tasks_v2` 方法），具有以下特性：

- **从目标点进行 BFS 探索**：确保所有出生点都与目标连通
- **距离约束的虚拟链接**：增强全景图之间的连接性
- **批量生成**：同一目标可生成多个不同出生点的任务
- **多目标复用**：支持在同一白名单内搜索多个 POI 目标，提高全景图复用率

---

## 三、任务生成详细流程

以下是完整的任务生成执行步骤：


### Step 1: POI 搜索

**目的**：在指定的中心坐标附近搜索符合条件的兴趣点。

**坐标获取方案**：
系统支持两种方式确定搜索中心 `(center_lat, center_lng)`：

| 方案 | 描述 | 适用场景 |
|------|------|----------|
| **A. 手动指定** | 用户直接提供一个坐标列表（List）作为输入 | 针对特定城市或区域进行测试 |
| **B. 自动生成** | 系统自动生成全球范围内的分散坐标点，覆盖不同大洲和区域 | 增加数据的多样性，捕捉全球各地不同的街景特色 |

> **自动生成实现逻辑**：
> 1. 预定义一个包含全球主要城市/区域的**边界框（Bounding Box）列表**（覆盖北美、欧洲、亚洲等主要街景覆盖区）。
> 2. 从列表中随机选择区域。
> 3. 在选定区域的经纬度范围内进行**均匀随机采样**。
> 4. 使用 Geocoding API 或简单的陆地/海洋检查（可选）确保点位于陆地上。

**搜索循环与错误处理**：

| 模式 | 行为逻辑 |
|------|----------|
| **手动指定** | 遍历列表，如果某点未搜索到 POI 或无街景覆盖：<br>1. **报错**并记录日志 <br>2. **跳过**该点，继续处理列表中的下一个点 |
| **自动生成** | 设定目标生成数量（如 30 个），进入 `while` 循环：<br>1. 随机生成一个坐标点 <br>2. 搜索 POI，如果失败（无结果/无街景）则**报错并自动重试**（重新生成新坐标）<br>3. 直到成功生成的有效点数量达到目标值（可自定义）为止 |

**过程**：

1. 接收输入参数：
   - `center_lat` / `center_lng`：搜索中心坐标
   - `poi_type`：POI 类别（如 `restaurant`、`transit` 等）
   - `poi_keyword`：具体关键词（如 `"McDonald's"`）

2. 调用 `POISearcher.search_nearby()` 方法：
   - 如果提供了 `keyword`：使用 **Text Search API** 进行精确名称匹配
   - 如果没有提供 `keyword`：使用 **Places API (New)** 进行类型搜索
   - 搜索半径默认为 1500 米（可通过配置修改）
   - **重试机制**：如果请求失败，系统会自动**重试 3 次**（共 4 次尝试），每次间隔 2 秒

3. 调用 `POISearcher.enrich_with_pano_ids()` 为每个 POI 获取最近的街景全景图 ID：
   - 使用 **Street View Static API** 的 metadata 端点
   - 过滤掉没有街景覆盖的 POI

**输出**：一个 POI 列表，每个 POI 包含：
- `place_id`：Google Places ID
- `name`：地点名称
- `lat` / `lng`：坐标
- `nearest_pano_id`：最近的全景图 ID

---

### Step 2: 寻找具有足够覆盖范围的目标

**目的**：从候选 POI 中选择一个具有足够街景覆盖的目标。

**过程**：
1. 随机打乱 POI 列表顺序（增加随机性）

2. 对每个 POI 尝试调用 `WhitelistGenerator.generate_from_target()` 方法：
   - 以目标全景图为起点进行 **BFS（广度优先搜索）**探索
   - 探索时遵循约束条件：
     - `min_panos`（默认 20）：最少需要发现的全景图数量
     - `max_panos`（默认 60）：最多探索的全景图数量
     - `max_distance`（默认 500 米）：距离目标的最大距离

3. BFS 探索过程：
   ```
   初始化：将目标全景图加入队列
   
   循环直到队列为空或达到 max_panos：
       取出队首全景图
       获取该全景图的元数据（通过 MetadataFetcher）
       计算该全景图与目标的距离
       如果距离 <= max_distance：
           将该全景图加入白名单
           获取其所有相邻链接（links）
           将未访问过的相邻全景图加入队列
   ```

4. 识别出生点候选：
   - 从白名单中筛选距离在 `[spawn_min_distance, spawn_max_distance]` 范围内的全景图
   - 默认范围为 100-200 米

5. 验证覆盖是否足够：
   - 白名单数量 >= `min_panos`
   - 出生点候选数量 >= 请求的 `spawn_count`

**输出**：
- `whitelist`：可行区域内的所有全景图 ID 列表
- `spawn_candidates`：符合距离要求的出生点候选列表
- `metadata_map`：每个全景图的元数据字典

---

### Step 3: 链接增强

**目的**：改善全景图之间的连接性，解决 Google API 链接不完整的问题。

**当前策略决定**：

| 项目 | 决定 | 说明 |
|------|------|------|
| **虚拟链接** | ✅ 保留 | 18 米内添加双向连接，heading 自动正确计算 |
| **距离修剪** | ❌ 不启用 | 不删除超过 20 米的连接 |
| **白名单外链接** | ✅ 删除 | 保存前过滤掉指向白名单外的链接 |
| **fix_reverse_headings()** | ❌ 不调用 | 避免数据损坏 |

**过程**：

#### 3a. 添加虚拟链接

调用 `LinkEnhancer.enhance_links()` 方法：

1. 遍历白名单中所有全景图对
2. 计算每对全景图之间的物理距离（使用 Haversine 公式）
3. 如果距离 ≤ **18 米**且不存在原生链接：
   - 创建一条双向虚拟链接
   - 计算从 A 到 B 的方向角（heading）
   - 链接格式与 Google API 一致

虚拟链接的数据结构：
```python
{
    "pano_id": "目标全景图ID",
    "heading": 45.0,        # 从当前点看向目标点的方向角（0-360）
    "distance": 15.5,       # 距离（米）
    "virtual": True         # 标记为虚拟链接
}
```

#### 3b. 过滤白名单外链接

保存到缓存前，移除所有指向白名单外全景图的链接：
- 确保 Agent 运行时只能导航到白名单内的节点
- 避免 Agent 走出可控区域

#### 3c. 保存增强后的元数据到缓存

- 将增强后的链接信息保存到 `metadata_cache`
- 运行时 Agent 可直接使用增强后的连接数据

> **注意**：`fix_reverse_headings()` 和距离修剪功能已禁用，以保持原始 Google API 数据的完整性。


---

### Step 4: 选择出生点（分散采样）

**目的**：从候选中选择指定数量（`spawn_count`）的出生点，并确保它们在空间上尽可能分散。

**策略**：采用 **Greedy Farthest Point Sampling (贪婪最远点采样)** 算法。

**过程**：

1. **第一个点**：从 `spawn_candidates` 中随机选择一个作为初始出生点。
2. **后续点**：
   - 对于每个剩余的候选点，计算它与**已选点集合**中最近点的距离。
   - 选择那个**距离已选集合最远**的候选点加入集合。
   - 重复直到达到 `spawn_count`。

**优势**：
- 避免出生点聚集在同一侧
- 确保测试覆盖了目标周围的不同方向和路径特征
- 适用于主目标和次要目标任务生成

**示例**（spawn_count=3）：
- 点 A：随机选中（目标北侧）
- 点 B：选离 A 最远的点（通常在目标南侧）
- 点 C：选离 A 和 B 都最远的点（通常在目标东西侧）


### Step 5: 生成任务数据

**目的**：为每个出生点创建完整的任务描述。

**过程**：

对于每个选中的出生点：

1. **计算初始朝向**：
   - 根据出生点和目标点的坐标，计算从出生点指向目标的方向角
   - 使用球面几何公式：`atan2(sin(Δlng)·cos(lat2), cos(lat1)·sin(lat2) - sin(lat1)·cos(lat2)·cos(Δlng))`

2. **获取导航路线**：
   - 调用 `DirectionsFetcher.get_route()` 获取步行路线
   - 使用 **Google Routes API (New)** 
   - 请求参数：起点坐标、终点坐标、出行方式（WALK）
   - **重试机制**：如果 API 调用失败，系统会自动**重试 3 次**（共 4 次尝试）

3. **生成任务描述**：
   - 调用 `DirectionsFetcher.generate_task_description()` 
   - 将路线步骤转换为自然语言描述
   - **关键：移除街道名称**，只保留方向指令（如"左转"、"直行"）
   
   示例：
   ```
   原始指令: "Turn left onto Main Street, then walk 200m"
   简化后: "Turn left, then walk 200m"
   ```

4. **组装任务 JSON**：

```json
{
    "task_id": "nav_mcdonalds_20260116_134537_1",
    "task_type": "navigation_to_poi",
    "geofence": "list_nav_mcdonalds_20260116_134537",
    "spawn_point": "全景图ID",
    "spawn_heading": 135,
    "description": "自然语言导航描述...",
    "ground_truth": {
        "target_name": "McDonald's",
        "target_pano_id": "目标全景图ID",
        "optimal_path_length": 8,
        "optimal_distance_meters": 156,
        "route_description": "straight→left→straight"
    },
    "answer": "",
    "target_pano_ids": ["目标全景图ID"],
    "max_steps": null,
    "max_time_seconds": 300
}
```

---

### Step 6: 保存文件

**生成的文件**：

#### 任务文件
- 路径：`tasks/{task_id}.json`
- 内容：完整的任务定义

#### 白名单配置
- 路径：`config/geofence_config.json`
- 格式：
```json
{
    "list_nav_mcdonalds_20260116_134537": [
        "pano_id_1",
        "pano_id_2",
        "pano_id_3",
        // ... 所有可行区域的全景图 ID
    ]
}
```

#### 可视化分布图
- 路径：`vis/{geofence_name}_network.html`
- 命名：以此批次任务共享的白名单（geofence）名称命名（例如 `list_nav_mcdonalds_..._network.html`）
- 功能：交互式全景图分布与连接可视化
- 特性：
  - 显示所有白名单内的全景图点位
  - **交互功能**：点击任意点，高亮显示与其相连的所有点（绿色）
  - 辅助验证：直观检查 BFS 探索范围和连通性

---

### Step 7: 验证与完成

系统输出最终的任务统计信息，包括生成的任务数量、全景图总数、添加的虚拟链接数等。

---

## 四、关键参数说明

### 4.1 CLI 调用参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `--center-lat` | float | 必填 | 搜索中心纬度 |
| `--center-lng` | float | 必填 | 搜索中心经度 |
| `--poi-type` | string | 必填 | POI 类别 |
| `--poi-keyword` | string | 可选 | 具体 POI 名称 |
| `--v2` | flag | - | 使用 V2 算法 |
| `--spawn-count` | int | 2 | 生成的任务数量 |
| `--min-panos` | int | 20 | 最小全景图数量 |
| `--max-panos` | int | 60 | 最大探索全景图数量 |
| `--max-distance` | float | 500 | 最大探索距离（米） |
| `--spawn-min` | int | 100 | 出生点最小距离（米） |
| `--spawn-max` | int | 200 | 出生点最大距离（米） |
| `--virtual-link-threshold` | float | 20 | 虚拟链接距离阈值（米） |

### 4.2 POI 配置示例

在 `poi_config.json` 中定义：

```json
{
    "poi_categories": {
        "restaurant": {
            "keywords": ["McDonald's", "KFC", "Starbucks", "Subway"],
            "places_type": "restaurant"
        },
        "transit": {
            "keywords": ["bus stop", "subway station", "metro station"],
            "places_type": ["bus_station", "transit_station"]
        }
    },
    "generation_defaults": {
        "spawn_distance_min": 100,
        "spawn_distance_max": 250,
        "search_radius": 1500
    }
}
```

---

## 五、数据流向图

```
                    用户输入参数
                        │
                        ▼
            ┌─────────────────────┐
            │   POISearcher       │
            │  (Google Places API)│
            └─────────┬───────────┘
                      │ POI 列表
                      ▼
            ┌─────────────────────┐
            │   enrich_with_      │
            │   pano_ids()        │
            │  (Street View API)  │
            └─────────┬───────────┘
                      │ 带全景ID的POI
                      ▼
            ┌─────────────────────┐
            │  WhitelistGenerator │
            │   (BFS 探索)        │
            └─────────┬───────────┘
                      │ 白名单 + 出生点候选
                      ▼
            ┌─────────────────────┐
            │   LinkEnhancer      │
            │ (添加虚拟链接)      │
            └─────────┬───────────┘
                      │ 增强后的元数据
                      ▼
            ┌─────────────────────┐
            │  DirectionsFetcher  │
            │ (Google Routes API) │
            └─────────┬───────────┘
                      │ 导航路线和描述
                      ▼
            ┌─────────────────────┐
            │   TaskAssembler     │
            │  (组装 + 保存)      │
            └─────────┬───────────┘
                      │
            ┌─────────┴─────────┐
            ▼                   ▼
    tasks/{task_id}.json   geofence_config.json
```

---

## 六、元数据获取与缓存

### 6.1 MetadataFetcher

负责获取单个全景图的详细元数据：
- **数据来源**：通过 Selenium 模拟访问 Google Maps，解析 JavaScript 返回的元数据
- **重试机制**：如果首次获取失败（如网络波动或加载超时），系统会自动**重试 3 次**（共 4 次尝试），每次重试前等待 2 秒。
- **获取的信息**：
  - 全景图 ID
  - 坐标（lat, lng）
  - 拍摄日期
  - 相邻链接（links）：每个链接包含目标 pano_id 和 heading
  - center_heading（图像中心对应的方向角）

### 6.2 metadata_cache

- **存储位置**：`cache/pano_metadata.json`
- **作用**：避免重复请求，加速 BFS 探索
- **格式**：
```json
{
    "pano_id_xxx": {
        "lat": 47.506123,
        "lng": 19.055678,
        "capture_date": "2023-06",
        "center_heading": 180.0,
        "links": [
            {"pano_id": "yyy", "heading": 45.0},
            {"pano_id": "zzz", "heading": 225.0}
        ],
        "last_accessed": 1705385678
    }
}
```

---

## 七、复现步骤

### 7.1 环境准备

1. 安装依赖：
```bash
pip install -r requirements.txt
```

2. 配置 API 密钥（在 `.env` 文件中）：
```
GOOGLE_API_KEY=your_api_key_here
```

### 7.2 运行命令示例

生成麦当劳导航任务（布达佩斯市中心，2个出生点）：

```bash
python scripts/generate_tasks.py --v2 \
    --center-lat 47.5065 \
    --center-lng 19.0551 \
    --poi-type restaurant \
    --poi-keyword "McDonald's" \
    --spawn-count 2 \
    --min-panos 20 \
    --max-panos 60 \
    --max-distance 500 \
    --spawn-min 100 \
    --spawn-max 200
```

### 7.3 预期输出

```
============================================================
*** Task Generation V2 Pipeline
============================================================

[*] Step 1: Searching for POI...
  Found 3 POIs with Street View coverage

[*] Step 2: Finding target with sufficient coverage...
  Trying POI 1/3: McDonald's - Deák Ferenc tér
  [OK] Selected target: McDonald's - Deák Ferenc tér

[*] Step 3: Enhancing panorama links...
  [OK] Added 12 virtual links, pruned 3 distant links
  [OK] Fixed 5 reverse heading mismatches
  [OK] Saved enhanced links for 45 panoramas to cache

[*] Step 4: Selecting 2 spawn points...
  Spawn 1: CAoSLEFGMVFp... (distance: 156m)
  Spawn 2: CAoSLEFGMVFp... (distance: 178m)

[*] Step 5: Generating 2 tasks...

[*] Step 6: Saving whitelist...
  [OK] Updated whitelist: list_nav_mcdonalds_... (45 panos)

============================================================
[OK] Task Generation V2 Complete!
============================================================
  Target: McDonald's - Deák Ferenc tér
  Tasks generated: 2
  Whitelist: 45 panoramas
  Virtual links: 12
  - nav_mcdonalds_20260116_134537_1
  - nav_mcdonalds_20260116_134537_2
============================================================
```

---

## 八、常见问题与解决方案

| 问题 | 可能原因 | 解决方案 |
|------|----------|----------|
| "No POIs found" | 该区域没有符合条件的 POI | 尝试不同的 `poi_keyword` 或扩大搜索半径 |
| "No POIs have Street View coverage" | 选中的 POI 附近没有街景 | 换一个地区或不同的 POI |
| "Not enough spawn candidates" | 覆盖区域太小 | 增大 `max_distance` 或降低 `spawn_min_distance` |
| 元数据获取失败 | Selenium 或 API 限制 | 添加延迟、检查网络连接 |

---

## 九、多目标 POI 搜索与白名单复用

为了提高全景图的复用率，系统支持在同一白名单内搜索多个不同的 POI 目标。

### 9.1 设计思路

在建立一个目标（如 McDonald's）的白名单后，可以在同一覆盖区域内搜索其他 POI（如 Starbucks），复用已探索的全景图数据。

### 9.2 搜索策略

| 搜索类型 | 搜索中心 | 搜索半径 | 说明 |
|----------|----------|----------|------|
| **主目标搜索** | 用户指定的 `(center_lat, center_lng)` | 默认 1500m | 由近及远寻找第一个符合条件的 POI |
| **次要目标搜索** | 主目标 POI 的坐标 `(target_poi.lat, target_poi.lng)` | `max_distance`（白名单探索半径，默认 500m） | 在白名单覆盖范围内搜索 |

### 9.3 次要目标验证流程

```
1. 以主目标 POI 坐标为中心，调用 Places API 搜索次要关键词
   - 搜索半径 = max_distance（即白名单的 BFS 探索半径）
   
2. 对返回的每个 POI，获取其 nearest_pano_id

3. 验证：nearest_pano_id 是否在白名单中？
   - 如果在 → 该 POI 可用，复用同一白名单生成任务
   - 如果不在 → 跳过该 POI
```

### 9.4 可视化示意

```
         用户指定中心 ○ ← 搜索主目标时的圆心（1500m 半径）
              │
              │ (可能偏移几百米)
              ▼
          🍔 McDonald's ← 主目标 POI 坐标
              │
     ┌────────┼────────┐
     │   max_distance  │ ← 500m 白名单探索半径
     │  ╱             ╲ │   也是次要目标搜索半径
     │ ☕ Starbucks    │ ← 次要目标（nearest_pano 在白名单内 ✓）
     │  ╲   白名单    ╱ │
     │   ╲   区域   ╱   │
     └────────────────┘
            🍕 Pizza Hut  ← 不在白名单范围内 ✗
```

### 9.5 多目标调用示例

```python
# 主目标搜索
primary_pois = await poi_searcher.search_nearby(
    lat=center_lat,           # 用户指定的中心坐标
    lng=center_lng,
    poi_type="restaurant",
    keyword="McDonald's",
    radius_meters=1500        # 大范围寻找主目标
)

# ... 选择主目标，生成白名单 ...

# 次要目标搜索
secondary_pois = await poi_searcher.search_nearby(
    lat=target_poi.lat,       # 主目标 POI 的坐标
    lng=target_poi.lng,
    poi_type="restaurant",
    keyword="Starbucks",
    radius_meters=max_distance  # 白名单探索半径（500m）
)

# 过滤：只保留 nearest_pano_id 在白名单中的 POI
valid_secondary = [
    poi for poi in secondary_pois 
    if poi.nearest_pano_id in whitelist
]
```

### 9.6 产出格式

多目标模式下，**每个**成功找到并验证的 POI 目标（无论是主目标还是次要目标），都会生成 `spawn_count` 个任务。所有任务共享同一个白名单（geofence）。

**任务生成数量规则**：
- 总任务数 = (主目标数 + **有效次要目标数**) × spawn_count
  > 这里的“有效次要目标”指：Places API 搜索均能返回且 `nearest_pano_id` 位于白名单内的 POI。

**白名单配置**：
```json
{
    "list_nav_batch_20260119": ["pano_1", "pano_2", ...]
}
```

**生成的任务文件示例**（假设 spawn_count = 3）：
- **主目标：McDonald's**
  - `nav_mcdonalds_..._1.json`
  - `nav_mcdonalds_..._2.json`
  - `nav_mcdonalds_..._3.json`
- **次要目标：Starbucks**（复用白名单）
  - `nav_starbucks_..._1.json`
  - `nav_starbucks_..._2.json`
  - `nav_starbucks_..._3.json`


### 9.7 搜索 API 选择

系统使用两种不同的 Google Places API，各有特点：

| API | 使用场景 | 半径行为 | 关键词支持 |
|-----|---------|---------|-----------|
| **Text Search** | 主目标搜索（品牌名称） | `locationBias`：偏好范围，非严格限制 | ✅ 支持 |
| **Nearby Search** | 次要目标搜索（类型） | `locationRestriction`：严格限制 | ❌ 不支持 |

**建议策略**：
- **主目标**：使用 Text Search 搜索特定品牌（如 "McDonald's"）
- **次要目标**：使用 Nearby Search 按类型搜索，再通过 `nearest_pano_id ∈ 白名单` 验证

### 9.8 推荐的次要目标类型

由于 Nearby Search 不支持关键词，次要目标应选择**视觉特征明显、不需要看店名就能识别**的类型：

**✅ 推荐类型（易识别）**：

| 类型 | places_type | 街景中的识别特征 |
|------|-------------|----------------|
| **加油站** | `gas_station` | 顶棚、油泵、品牌标志 |
| **银行/ATM** | `bank`, `atm` | 大型招牌、ATM 机器 |
| **药房** | `pharmacy` | 绿色/红色十字标志（国际通用） |
| **医院** | `hospital` | 红十字、大型建筑 |
| **公交站** | `bus_station`, `transit_station` | 站台、候车亭、路牌 |
| **教堂** | `church` | 尖顶、十字架 |
| **停车场** | `parking` | P 标志、栏杆、收费亭 |
| **邮局** | `post_office` | 统一颜色和标志 |
| **超市** | `supermarket` | 大型建筑、购物车 |

**❌ 不推荐类型**：

| 类型 | 原因 |
|------|------|
| `restaurant` | 太多小店，招牌可能被遮挡或不清晰 |
| `cafe` | 需要识别具体品牌名 |
| `store` | 种类太多，难以区分 |

### 9.9 建议的目标组合

```
主目标（Text Search）      次要目标（Nearby Search）
─────────────────────      ─────────────────────────
McDonald's, KFC,           gas_station, pharmacy,
Starbucks, Subway   +      bank, bus_station,
等品牌连锁店               hospital, church
```

这样主目标通过品牌名称精确匹配，次要目标通过类型特征识别，无需依赖店名。

---

## 十、探索发现型任务（Exploration Task）

除了路线引导型的 `navigation_to_poi` 任务外，系统还支持一种**探索发现型任务**，要求 Agent 在区域内自由探索寻找目标 POI，并回答是否找到。

> **注意**：Exploration tasks 应该是在生成 Navigation tasks 的时候顺带产生的

### 10.1 任务类型对比

| 特性 | 路线引导型 (`navigation_to_poi`) | 探索发现型 (`exploration_find_poi`) |
|------|----------------------------------|-------------------------------------|
| **任务描述** | 包含具体导航指令（左转、直行等） | 只描述目标特征，不提供路线 |
| **Agent 行为** | 遵循指令到达目标 | 自主探索区域寻找目标 |
| **答案格式** | 无需回答问题 | 回答 `yes` 或 `no` |
| **终止条件** | 到达目标附近 | Agent 主动调用 `stop` 并提交答案 |

### 10.2 任务设计

探索发现型任务包含两种子类型：

#### 正例任务（Positive Example）
- **条件**：区域内**存在**目标 POI
- **预期行为**：Agent 探索区域，找到目标后停在其前方，回答 `yes`
- **ground_truth.answer**：`"yes"`

#### 反例任务（Negative Example）
- **条件**：区域内**不存在**目标 POI
- **预期行为**：Agent 探索区域后确认目标不存在，回答 `no`
- **ground_truth.answer**：`"no"`

### 10.3 任务描述示例

**正例描述**（区域内有麦当劳）：
```
你现在位于一个城市街区中。请在这个区域内寻找是否有麦当劳餐厅。
如果找到，请走到麦当劳门前并停下，回答 "yes"。
如果探索完整个区域后确认没有麦当劳，请回答 "no"。
```

**反例描述**（区域内没有 Starbucks）：
```
你现在位于一个城市街区中。请在这个区域内寻找是否有星巴克咖啡店。
如果找到，请走到星巴克门前并停下，回答 "yes"。
如果探索完整个区域后确认没有星巴克，请回答 "no"。
```

### 10.4 生成逻辑

#### 正例任务生成

```
1. 主目标搜索 → 找到 McDonald's
2. BFS 探索 → 生成白名单
3. 选择出生点 → 使用贪婪最远点采样
4. 生成任务：
   - task_type: "exploration_find_poi"
   - description: 探索寻找描述（不含路线指令）
   - ground_truth.answer: "yes"
   - target_pano_ids: [目标全景图ID]
```

#### 反例任务生成

```
1. 主目标搜索 → 找到 McDonald's
2. BFS 探索 → 生成白名单
3. 次要目标搜索（如 Starbucks）→ 验证 nearest_pano_id 是否在白名单内
4. 如果次要目标 **不在白名单内**：
   - 生成反例任务
   - task_type: "exploration_find_poi"
   - description: 探索寻找描述
   - ground_truth.answer: "no"
   - target_pano_ids: []  // 空，因为区域内没有目标
5. 选择出生点 → 复用主目标白名单的出生点候选
```

### 10.5 目标唯一性验证（预检）

为避免评估歧义，**必须确保白名单范围内只有唯一一个目标 POI**。

#### 问题场景

```
白名单区域（500m 半径）：
    🍔 McDonald's A ← nearest_pano: pano_1
         |
    🍔 McDonald's B ← nearest_pano: pano_2
         |
    ★ Agent 出生点
```

如果区域内有两家麦当劳，Agent 找到任意一家都算正确，但评估时无法确定 Agent 应该到达哪个 `target_pano_id`。

#### 检查时机（优化）

> [!TIP]
> **关键优化**：在 BFS 探索**之前**进行唯一性预检，可以避免在无效候选上浪费探索时间。

| 时机 | 优势 | 说明 |
|------|------|------|
| ❌ BFS 之后 | - | 如果有重复，前面的 BFS 工作白费 |
| ✅ **BFS 之前** | 节省时间 | 搜索中心 = 主目标坐标，搜索半径 = `max_distance` |

**预检逻辑**：

```
Step 1: POI 搜索 → 找到 McDonald's A（坐标: lat_A, lng_A）
         ↓
Step 1.5: 唯一性预检 ← 新增步骤
         - 搜索中心: (lat_A, lng_A)
         - 搜索半径: max_distance（即白名单 BFS 范围，默认 500m）
         - 搜索关键词: 与主目标相同（"McDonald's"）
         - 如果返回 ≥2 个结果 → 跳过该候选，尝试下一个
         ↓
Step 2: BFS 探索 → 生成白名单（只有通过预检才执行）
```

#### 验证代码

```python
def pre_check_unique_target(primary_poi, poi_searcher, max_distance):
    """
    在 BFS 探索之前，预检白名单范围内是否只有唯一的目标 POI。
    
    Args:
        primary_poi: 已找到的主目标 POI
        poi_searcher: POI 搜索器实例
        max_distance: 白名单 BFS 探索半径（米）
    
    Returns:
        bool: True = 唯一（可继续生成），False = 有重复（应跳过）
        int: 该范围内的同类 POI 数量
    """
    # 以主目标坐标为中心，max_distance 为半径，搜索同关键词的 POI
    same_keyword_pois = poi_searcher.search_nearby(
        lat=primary_poi.lat,
        lng=primary_poi.lng,
        keyword=primary_poi.keyword,  # 使用相同关键词
        radius_meters=max_distance    # 与 BFS 探索范围一致
    )
    
    # 返回的结果已经是该半径内的所有同名 POI
    count = len(same_keyword_pois)
    is_unique = (count == 1)
    
    return is_unique, count
```

#### 集成到生成流程

```python
# Step 1: 搜索主目标
primary_pois = poi_searcher.search_nearby(
    lat=center_lat, lng=center_lng,
    keyword="McDonald's", radius_meters=1500
)

for poi in primary_pois:
    # Step 1.5: 唯一性预检（在 BFS 之前！）
    is_unique, count = pre_check_unique_target(poi, poi_searcher, max_distance=500)
    
    if not is_unique:
        logger.warning(f"Skipping {poi.name}: {count} '{poi.keyword}' found within {max_distance}m")
        continue  # 跳过，尝试下一个候选
    
    # Step 2: 通过预检，继续 BFS 探索
    whitelist, spawn_candidates = whitelist_generator.generate_from_target(poi.nearest_pano_id)
    
    # ... 后续步骤 ...
```

#### 处理策略

| 预检结果 | 处理方式 |
|----------|----------|
| **唯一**（1 个） | ✅ 继续 BFS 探索和任务生成 |
| **重复**（≥2 个） | ⚠️ 跳过该候选，尝试列表中下一个 POI |

> [!NOTE]
> 由于预检发生在 BFS 之前，我们不需要验证 `nearest_pano_id` 是否在白名单内 —— 此时白名单尚未生成。
> 但由于搜索半径与 `max_distance` 一致，范围内的 POI 大概率会落入白名单。

### 10.6 任务 JSON 格式

#### 正例任务

```json
{
    "task_id": "exp_mcdonalds_20260119_223000_1",
    "task_type": "exploration_find_poi",
    "geofence": "list_exp_mcdonalds_20260119_223000",
    "spawn_point": "全景图ID",
    "spawn_heading": 135,
    "description": "你现在位于一个城市街区中。请在这个区域内寻找是否有麦当劳餐厅。如果找到，请走到麦当劳门前并停下，回答 yes。如果探索完整个区域后确认没有麦当劳，请回答 no。",
    "ground_truth": {
        "target_name": "McDonald's",
        "target_pano_id": "目标全景图ID",
        "answer": "yes"
    },
    "answer": "",
    "target_pano_ids": ["目标全景图ID"],
    "max_steps": null,
    "max_time_seconds": 600
}
```

#### 反例任务

```json
{
    "task_id": "exp_starbucks_20260119_223000_1",
    "task_type": "exploration_find_poi",
    "geofence": "list_exp_mcdonalds_20260119_223000",
    "spawn_point": "全景图ID",
    "spawn_heading": 135,
    "description": "你现在位于一个城市街区中。请在这个区域内寻找是否有星巴克咖啡店。如果找到，请走到星巴克门前并停下，回答 yes。如果探索完整个区域后确认没有星巴克，请回答 no。",
    "ground_truth": {
        "target_name": "Starbucks",
        "target_pano_id": null,
        "answer": "no"
    },
    "answer": "",
    "target_pano_ids": [],
    "max_steps": null,
    "max_time_seconds": 600
}
```

### 10.7 出生点生成

每个任务的出生点都是**独立重新生成**的，使用相同的贪婪最远点采样算法：

1. 使用主目标白名单的 `spawn_candidates`
2. 根据 `spawn_count` 参数选择分散的出生点
3. **每个任务独立采样**：正例和反例任务各自重新生成出生点，不共享

### 10.8 终止条件与评估标准

#### 终止条件

| 条件 | 说明 |
|------|------|
| **Agent 主动停止** | Agent 随时可调用 `stop` 并提交答案（`yes` 或 `no`） |
| **超时/超步** | 达到 `max_steps` 或 `max_time_seconds` 时强制终止 |

> [!NOTE]
> Agent 可以在**任何时刻**主动终止，只要它确信已找到目标或确认目标不存在。

#### 答案格式

- **有效答案**：`yes` 或 `no`
- **大小写**：不敏感（`Yes`, `YES`, `yes` 均有效）
- **语言**：仅支持英文，不接受中文“是”/“否”

#### 评估标准

| 指标 | 正例任务 | 反例任务 |
|------|----------|----------|
| **答案正确** | Agent 回答 `yes`（不区分大小写） | Agent 回答 `no`（不区分大小写） |
| **位置正确** | 最终位置**恰好在** `target_pano_ids` 中 | 不检查位置（无目标） |
| **任务成功** | 答案正确 **且** 位置正确 | 答案正确即可 |

> [!IMPORTANT]
> 正例任务的位置验证是**精确匹配**：Agent 的最终全景图 ID 必须在 `target_pano_ids` 列表中，而不是“附近”。

### 10.9 反例目标选择建议

为确保反例任务的合理性，建议选择以下类型的 POI 作为反例目标：

**✅ 推荐用于反例**：
- 特定品牌连锁店（容易确认是否存在）
- 视觉特征明显的 POI 类型

**❌ 避免用于反例**：
- 通用类型（如"餐厅"）— Agent 难以穷尽搜索
- 在该地区极为常见的 POI — 容易误判

### 10.10 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--exploration-mode` | false | 生成探索发现型任务 |
| `--spawn-count` | 2 | 每种任务（正例/反例）的出生点数量 |
| `--negative-keywords` | [] | 用于生成反例的次要 POI 关键词列表 |
| `--max-steps` | None | 探索任务允许的最大步数（暂不设置限制） |
| `--max-time-seconds` | 600 | 探索任务允许的最大时间（10分钟） |

### 10.11 CLI 调用示例

```bash
python scripts/generate_tasks.py --v2 \
    --center-lat 47.5065 \
    --center-lng 19.0551 \
    --poi-type restaurant \
    --poi-keyword "McDonald's" \
    --exploration-mode \
    --spawn-count 2 \
    --negative-keywords "Starbucks" "KFC"
```

**预期输出**：
- 2 个正例任务（找麦当劳，答案 yes）
- 若 Starbucks/KFC 不在白名单内 → 各生成 2 个反例任务（答案 no）

---

## 十一、总结

任务生成系统的核心流程可以概括为：

1. **搜索** → 找到地图上的主目标 POI
2. **探索** → 从目标出发 BFS 构建可行区域（白名单）
3. **增强** → 添加虚拟链接改善连通性
4. **复用** → 在白名单范围内搜索次要目标 POI（可选）
5. **生成** → 为每个目标的每个出生点创建任务描述
6. **保存** → 输出 task.json 和共享的 whitelist

整个过程自动化程度高，只需提供中心坐标和 POI 类型即可生成完整的导航任务数据。多目标复用机制可显著减少 API 调用和元数据获取次数。
