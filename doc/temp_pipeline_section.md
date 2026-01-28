
## 7. 任务生成与存储 (Pipeline & Storage)
*   **存储路径**：新建专门的文件夹 `tasks_building_height/` 专门用于存储此类任务的数据。
*   **图像预下载 (Image Pre-fetching)**：
    *   **时机**：在生成 Whitelist 后，**立即调用 API** 下载白名单中（包括 Spawn 点和所有通过 BFS 找到的点）的图像。
    *   **参数**：默认下载 **Level 2** (Zoom Level 2) 的全景图切片。
    *   **目的**：确保 VLN 任务执行时直接读取本地图片，避免实时网络请求延迟，同时为 VLM 描述生成提供高清晰度素材。
