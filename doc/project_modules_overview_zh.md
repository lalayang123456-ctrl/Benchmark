# VLN Benchmark 项目模块详解

本文档详细介绍了 Visual Language Navigation (VLN) Benchmark 项目的各个核心功能模块。该系统旨在提供一个逼真的、可交互的仿真环境，用于生成导航任务、执行智能体（Agent）评估以及可视化分析。

## 1. 数据生成模块 (Data Generation Module)

**对应目录**: `data_generator/`, `building_height_generator/`, `spatial_orientation_generator/`, `visual_data_generator/`

该模块负责构建 Benchmark 所需的多样化测试任务集，不局限于传统的导航任务，还扩展到了视觉探索和物理属性感知等领域。

### 1.1 支持的任务类型 (Task Types)

系统支持以下四类核心任务的自动化生成：

1.  **导航任务 (Navigation Tasks)**:
    *   **目标**: 根据自然语言指令到达指定 POI (如 "Walk to McDonald's")。
    *   **生成逻辑**: 利用 Google Maps Routes API 生成真实路径指令，结合街景网络构建导航图。
2.  **视觉探索任务 (Visual Exploration Tasks)**:
    *   **目标**: 在没有显式路径指令的情况下，仅凭视觉线索（如路牌、地标）寻找目标。
    *   **生成逻辑**: 侧重于生成视觉连通性强但缺乏明确文本指令的路径，用于测试 Agent 的纯视觉探索能力。
3.  **建筑物高度估算任务 (Building Height Estimation)**:
    *   **目标**: 评估 Agent 对环境物理属性的感知能力（例如：“这栋楼大约有多少层？”）。
    *   **生成逻辑**: 结合 GIS 数据或人工标注的 Ground Truth，生成针对特定建筑物的问答任务。
4.  **空间感知任务 (Spatial Perception Tasks)**:
    *   **目标**: 测试 Agent 的空间定位和方位感（例如：“起始点位于当前位置的什么方向？”）。
    *   **生成逻辑**: 基于全景图的地理坐标关系，生成方位判断和相对位置推理任务。

### 1.2 核心算法详解 (Algorithm Details)

为了保证生成的任务既具有挑战性又符合真实物理环境，系统我们在数据生成阶段实现了多项关键算法：

#### A. 各向同性探索 (Isotropic BFS Exploration)
*   **代码实现**: `whitelist_generator.py` -> `_sort_queue_by_direction_diversity`
*   **问题背景**: 普通的广度优先搜索 (BFS) 往往倾向于沿着主干道（即全景图连接最密集的街道）快速延伸，导致生成的导航图呈现细长条状，缺乏空间上的广度。
*   **算法逻辑**:
    1.  将搜索空间划分为 8 个 **45° 扇区** (N, NE, E, SE, S, SW, W, NW)。
    2.  在 BFS 队列中，不仅仅按入队顺序处理，而是通过**轮询 (Round-Robin)** 的方式从每个扇区中交替取出节点进行扩展。
    3.  **效果**: 确保探索范围是以目标点为中心的近似圆形区域（各向同性），而非单一方向的线性延伸，从而生成的起始点分布更加均匀。

#### B. 虚拟链接增强 (Virtual Link Enhancement)
*   **代码实现**: `link_enhancer.py`
*   **阈值**: **18.0 米**
*   **背景**: Google Street View 的原生连接数据（Links）有时不完整，某些相邻的全景点虽然视觉上互通，但数据层面缺乏连接。
*   **逻辑**: 计算 `whitelist` 内所有全景点对之间的 **Haversine 距离**。如果距离小于 18 米且原生链接不存在，系统会自动添加双向的“虚拟链接”。这确保了 Agent 不会因为数据缺失而被困在某些死胡同中。

#### C. 视觉任务生成流程 (Visual Task Generation Pipeline)
*   **代码实现**: `run_agent_visual_v2.py`
*   **目的**: 将不仅包含噪音的地图数据转化为高质量的、纯视觉驱动的导航指令。
*   **流程**:
    1.  **渲染 (Render)**: 根据原始任务路径，下载并渲染序列化的全景图像帧。
    2.  **视觉过滤 (Visual Filtering)**: 将图像序列连同原始（可能含有噪音）的地图指令输入给多模态大模型 (Gemini-Pro-Vision)。
    3.  **Prompt 约束**: 强制模型忽略不可见的“微小转弯”（Micro-turns），仅保留视觉上显著的地标和动作。
    4.  **输出**: 生成不包含显式路名、方向指引，主要依赖视觉描述（如“走向红色的邮筒”）的新指令。

### 1.3 任务数据结构 (Data Structure)

系统生成的标准任务 JSON 文件 (`tasks/*.json`) 包含以下关键字段：

```json
{
  "task_id": "nav_mcdonalds_2026...",   // 唯一任务标识
  "task_type": "navigation_to_poi",     // 任务类型
  "geofence": "list_nav_...",           // 对应的全景图白名单 ID
  "spawn_point": "pano_abc123...",      // 起始全景图 ID
  "spawn_heading": 135.0,               // 起始朝向
  "description": "Navigate to...",      // 导航指令 (Prompt)
  "ground_truth": {
    "target_pano_id": "pano_xyz789",    // 目标全景图 ID
    "optimal_distance_meters": 156.5,   // 最短路径距离
    "target_name": "McDonald's"
  },
  "max_steps": 50,                      // 最大步数限制
  "max_time_seconds": 300               // 时间限制
}
```

## 2. 核心仿真引擎模块 (Core Engine Module)

**对应目录**: `engine/`

这是系统的运行时核心，负责维护仿真环境的状态、处理 Agent 的动作请求并返回环境观测（Observation）。

*   **核心功能**:
    *   **会话管理 (`SessionManager`)**: 管理每个正在运行的测试会话（Session）的生命周期，包括创建、暂停、恢复和终止。支持 "Agent" 和 "Human" 两种模式。
    *   **动作执行器 (`ActionExecutor`)**: 接收并执行具体的导航动作（如 `move`, `rotate`, `stop`）。它会验证动作的合法性（例如是否撞墙），更新智能体的位置和朝向。
    *   **观测生成器 (`ObservationGenerator`)**: 根据智能体当前的姿态（位置、朝向、俯仰角），动态生成视觉观测数据。
    *   **图像拼接与渲染 (`ImageStitcher`)**: 
        *   **机制**: 基于 Google Maps Tile API，按标准网格系统 (512x512 像素/瓦片) 下载图块。
        *   **渲染**: 支持不同缩放级别 (Zoom Levels 0-5)，将二维瓦片实时拼接为完整的 Equirectangular 全景图，或重投影为 Agent 视角的透视图像 (Perspective View)。
    *   **元数据获取 (`MetadataFetcher`)**: 异步获取全景节点的邻接关系、经纬度等元数据。

## 3. 后端 API 服务模块 (Backend API Module)

**对应目录**: `api/`

基于 FastAPI 框架主要提供 RESTful 接口，作为前端 UI 和后端仿真引擎之间的桥梁，同时也支持远程 Agent 通过 HTTP 请求接入系统。

*   **核心功能**:
    *   **会话控制接口**: 提供 `/session/create`, `/session/action`, `/session/end` 等端点，允许外部程序完全控制导航过程。
    *   **任务管理接口**: 提供任务列表查询、任务详情获取以及全景图预加载（Preload）功能。
    *   **状态查询**: 实时返回 Agent 当前的视觉图像、位置坐标和可选动作列表。

## 4. 网页前端交互系统 (Web UI System)

**对应目录**: `web_ui/`

该模块提供了一套可视化的交互界面，用于人类评估员介入、任务回放以及调试分析。

*   **核心组件**:
    *   **智能体回放系统 (`agent_replay.html` & `js/map_view.js`)**:
        *   **轨迹可视化**: 左侧集成 Leaflet 地图，实时绘制智能体的移动轨迹、起始点（绿色）和终点（红色）。
        *   **第一人称视角同步**: 右侧展示智能体在每一步看到的实际街景图像，支持播放、暂停和拖动进度条查看。
        *   **详细日志面板**: 显示每一步的动作类型、耗时、剩余可选动作以及 Agent 输出的推理文本（Reasoning）。
    *   **人类评估界面 (`human_eval.html`)**: 允许人类用户代替 Agent 在环境中进行导航，用于收集人类基准数据（Kyle Baseline）或验证任务的可行性。
    *   **API 客户端 (`js/api_client.js`)**: 封装了与后端通信的逻辑，实现前后端分离。

## 5. 评估模块 (Evaluation Module)

**对应目录**: `evaluation/`

该模块负责对 Agent 的完成情况进行定量评估，生成标准化的测试报告。

*   **核心指标**:
    *   **成功率 (Success Rate, SR)**: 智能体最终位置距离目标的误差小于阈值（通常为 10-20米）的比例。
    *   **路径长度加权成功率 (SPL)**: 综合考虑导航成功率和路径长度的效率指标。
    *   **Oracle 成功率**: 智能体轨迹中任意一点曾达到目标的比例。
    *   **导航误差 (Navigation Error)**: 终点与目标的测地线距离。

## 6. 辅助工具与脚本 (Scripts)

**对应目录**: `scripts/`

包含一系列用于项目维护和批量处理的实用脚本。

*   **功能示例**:
    *   `batch_generation/`: 批量生成大规模测试任务。
    *   `visualize_network.py`: 生成 HTML 文件可视化全景图的连通拓扑结构。
    *   `verify_heading.py` & `check_task_ids.py`: 用于数据完整性校验和错误排查。
