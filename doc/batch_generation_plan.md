# 批量生成 Pipeline 实施计划

## 目标
创建一个批量生成视觉导航任务的 Pipeline。该 Pipeline 将执行以下流程：
1.  随机选择一个城市（不重复）。
2.  寻找一个主要 POI。
3.  在同一区域内寻找次要 POI。
4.  生成导航任务（Navigation Tasks）。
5.  生成视觉任务（Visual Tasks，即下载全景图并渲染）。
6.  使用 Agent 进行验证。
7.  自动删除验证失败的任务。

## 需要用户审查的内容
> [!IMPORTANT]
> **并行与存储配置**:
> - **文件存储**: 请参考下文 "文件存储位置详解"。
> - **持久化计数**: 将创建一个 `generation_state.json` 文件来记录当前的全局任务 ID (Global ID) 和合格任务总数。
> - **并行策略**:
>   - **生成与验证解耦 (Producer-Consumer)**: 主线程只负责生成临时任务，**生成后立即提交到后台线程池**进行验证，不等待验证结果。
>   - **并发控制**: 使用 `ThreadPoolExecutor`，限制最大并发验证数为 **5**。
>   - **线程安全**: 更新全局 ID 和状态文件时需使用**文件锁 (File Lock)** 防止竞争。

**核心逻辑:**
1.  **城市选择**: 加载约 150 个全球城市的列表（从文件读取）。随机选择未访问过的城市（不重复）。
2.  **核心生成循环**:
    *   **寻找主要 POI (Primary)**:
        *   遍历主要 POI 类型列表。
        *   在城市范围内寻找。如果找不到，则尝试下一个类型。
        *   **如果遍历完所有类型仍未找到**：放弃该城市，回到步骤 1 换下一个城市。
    *   **生成白名单与主要任务**:
        *   找到主要 POI 后，生成连通性白名单 (Whitelist)。
        *   **生成任务**: 为该主要 POI 生成 **3 个出生点**（即 3 个任务）。
    *   **寻找次要 POI 与任务生成**:
        *   在**白名单范围内**寻找次要 POI。
        *   只要次要 POI 位于白名单内，就为其生成 **3 个出生点**（即 3 个任务）。
        *   此过程遍历所有次要 POI 类型。
3.  **全局状态管理 (Global State)**:
    *   在 `VLN_BENCHMARK/data/generation_state.json` 中维护状态：
        ```json
        {
          "total_qualified_tasks": 0,
          "next_global_id": 1,
          "target_count": 1000,
          "visited_cities": [],
          "pending_temp_files": [] 
        }
        ```
    *   **字段说明**:
        *   `visited_cities`: 已完成遍历的城市列表（防止重启后重复）。
        *   `pending_temp_files`: 记录已生成但尚未完成验证（或尚未清理）的临时任务文件路径。用于重启时的垃圾清理。
    *   **ID 回退/分配逻辑**: 为了确保 Task ID 连续且不浪费，**ID 仅在验证通过后分配**。
        *   生成阶段：使用临时文件名（如 `temp_{timestamp}_{poi}_{spawn_idx}.json`）。
        *   验证阶段：如果验证通过，读取当前 `next_global_id`，重命名文件为正式 ID，并递增计数器。
        *   如果不通过：直接删除临时文件，不消耗 ID。

4.  **任务生成与命名规范**:
    *   **Task ID**: `0001` (4位全局 ID)。
    *   **Spawn Index**: `1`, `2`, `3` (代表同一 POI 的不同出生点)。
    *   **Nav Task Filename**: `nav_{id}_{poi}_{date}_{time}_{spawn_idx}.json`
        *   Example: `nav_0001_mcdonalds_20260123_1530_1.json`
    *   **Visual Task Filename**: `visual_{id}_{poi}_{date}_{time}_{spawn_idx}.json`
        *   Example: `visual_0001_mcdonalds_20260123_1530_1.json`
    *   **Whitelist Storage**: 写入 `geofence_config.json`。
    *   **Task ID 策略**: 每个合格的 JSON 文件消耗一个独立的 ID。即同一个 POI 的 3 个出生点将占用 3 个 ID（如 0001, 0002, 0003）。

5.  **视觉验证流程 (异步并发)**:
    *   **主循环 (Producer)**:
        *   生成临时任务文件（Nav + Visual）。
        *   将任务路径加入 `pending_temp_files` 并保存。
        *   **提交** 任务给 `ThreadPoolExecutor`（最大并发 5）。
        *   **立即继续** 寻找下一个 POI/城市，**不等待** 验证结果。
    *   **验证工作线程 (Consumer)**:
        *   接收临时任务路径。
        *   调用 `run_agent_visual.run_agent_on_task`。
        *   检查 `agent_verification`。
        *   **If YES**:
            *   **获取文件锁** (确保线程安全)。
            *   读取并更新 `next_global_id`。
            *   重命名 JSON 文件及关联 Nav 任务为正式 ID 格式。
            *   更新 `total_qualified_tasks` +1。
            *   保存 `generation_state.json`。
            *   **释放锁**。
        *   **If NO**:
            *   删除 Visual Task JSON。
            *   删除 Nav Task JSON。
            *   **保留** 图片和 Whitelist (Config entry)。
        *   **Finally**:
            *   **获取文件锁**。
            *   从 `pending_temp_files` 移除该任务路径。
            *   **释放锁**。
6.  **安全与恢复机制 (Safety & Recovery)**:
    *   **启动检查 (Startup)**:
        *   加载 `generation_state.json`。
        *   **清理残留**: 检查 `pending_temp_files`。如果存在文件，视为上次异常退出的残留，执行**删除**操作，确保环境干净。清空该字段并保存。
        *   **过滤城市**: 从城市列表中移除 `visited_cities` 中的城市。
    *   **过程记录**:
        *   每当生成一组临时文件 (`nav + visual`) 后，立即更新 `pending_temp_files` 并保存状态。
        *   验证完成后（无论成功失败），从 `pending_temp_files` 中移除对应文件，如果是成功则同时更新 `last_global_id`。
        *   城市处理完毕后，将该城市加入 `visited_cities` 并保存。
    *   **优雅退出 (Graceful Shutdown)**:
        *   捕获 `SIGINT` (Ctrl+C)。
        *   如果在“生成中”：停止生成，清理当前不完整的内存数据（文件已由 `pending` 列表保护，下次启动会删）。
        *   如果在“验证中”：等待当前正在运行的验证进程结束（设置短暂超时），然后退出。

7.  **终端实时看板 (Terminal Dashboard)**:
    *   为了清楚展示后台线程状态，不使用简单的 `print/logging`，而是利用 `tqdm` 或定时刷新控制台来显示：
        *   **生成进度 (Producer)**: 当前城市 `[City Name]` | 总生成待验: `N`
        *   **验证进度 (Consumer)**:
            *   `Active Threads`: `[|||||  ]` (3/5)
            *   `Pending Queue`: `12`
            *   `Qualified/Total`: `150/500` (Success Rate: 30%)
            *   `Latest ID`: `0150`
    *   **实现建议**: 使用一个单独的 Monitor 线程每10秒刷新一次统计信息。

## 文件存储位置详解

| 文件类型 | 存储路径 (相对于根目录) | 命名示例 |
| :--- | :--- | :--- |
| **Navigation Task** | `VLN_BENCHMARK/tasks/` | `nav_0001_mcdonalds_20260123_1530_1.json` |
| **Visual Task** | `VLN_BENCHMARK/tasks/` | `visual_0001_mcdonalds_20260123_1530_1.json` |
| **Whitelist** | `VLN_BENCHMARK/config/geofence_config.json` | `N/A` (Saved inside config file) |
| **Task Images (Rendered)** | `VLN_BENCHMARK/visual_data_generator/images/{task_name}/` | `VLN_BENCHMARK/visual_data_generator/images/visual_0001_mcdonalds_20260123_1530/` |
| **Raw Panoramas** | `VLN_BENCHMARK/data/panoramas/` | `VLN_BENCHMARK/data/panoramas/{pano_id}.jpg` |
| **Generation State** | `VLN_BENCHMARK/data/` | `generation_state.json` |


### `VLN_BENCHMARK/visual_data_generator`

#### [MODIFY] [run_agent_visual.py](file:///c:/GitHub/StreetView/VLN_BENCHMARK/visual_data_generator/run_agent_visual.py)
*   修改 `run_agent_on_task` 函数，使其返回验证结果（True/False），以便调用方知道是否需要执行删除操作。（目前该函数仅打印到标准输出）。

## 验证计划

### 手动验证
1.  使用较小的限制条件（例如只跑 1 个城市）运行 Pipeline。
2.  检查 `VLN_BENCHMARK/tasks` 目录下是否生成了 `nav_*.json` 和 `visual_*.json` 文件。
3.  检查控制台输出 (`stdout`)，确认重试逻辑和清理逻辑是否正常触发。
4.  确认保留下来的 `visual_*.json` 文件的 `agent_verification` 状态为 "YES"（或确认 "NO" 的已被删除）。

### 自动化测试
*   使用 "dry-run" 模式或针对已知的必定存在的 POI 运行脚本，确保整体流程跑通。
