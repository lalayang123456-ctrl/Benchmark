"""
分析全景图渲染和 heading 的关系

问题：
- Task spawn_heading = 90（想让 agent 面朝东）
- Panorama centerHeading = 178（全景图中心点朝向接近南方）
- Three.js panorama viewer 中 lon=0 时显示的是全景图中心

关键洞察：
- 当 panoramaViewer.lon = 0 时，用户看到的是全景图的"中心"
- 这个中心在真实世界中朝向 centerHeading (178°)
- 要让用户看到真北 (0°)，需要设置 lon = -centerHeading
- 要让用户看到 heading X，需要设置 lon = X - centerHeading

公式：
  panorama_lon = agent_heading - centerHeading

验证：
- agent_heading = 90（面朝东）
- centerHeading = 178
- panorama_lon = 90 - 178 = -88 = 272（这才是正确的 lon 值）

当前问题：
- 系统直接把 agent_heading (90) 作为 panorama_lon 使用
- 这样用户实际看到的方向是 90 + 178 = 268（接近西北），不是东
"""
print(__doc__)
