# Open-RMF 接入说明

## 官方消息依据

本项目的适配器依据 Open-RMF 官方 `rmf_internal_msgs`：

- `FleetState.msg`: https://github.com/open-rmf/rmf_internal_msgs/blob/main/rmf_fleet_msgs/msg/FleetState.msg
- `RobotState.msg`: https://github.com/open-rmf/rmf_internal_msgs/blob/main/rmf_fleet_msgs/msg/RobotState.msg
- `Location.msg`: https://github.com/open-rmf/rmf_internal_msgs/blob/main/rmf_fleet_msgs/msg/Location.msg
- `RobotMode.msg`: https://github.com/open-rmf/rmf_internal_msgs/blob/main/rmf_fleet_msgs/msg/RobotMode.msg

仓库内的 `examples/open-rmf-fleet-state.json` 严格按这些消息字段编写，可直接导入页面或 POST 到实时接口。

## 无硬件模拟

从“我的产品”打开产品并取得根 URL，然后执行：

```bash
python3 tools/mock_rmf_source.py --url http://HOST:PORT
```

脚本每秒推送一帧包含三台机器人的官方结构 `FleetState`。实时页面会累积轨迹，并在停止推送 15 秒后显示数据延迟。

发送固定 20 帧用于测试：

```bash
python3 tools/mock_rmf_source.py --url http://HOST:PORT --count 20 --interval 0.2
```

## rosbridge 输入

适配器也接受 rosbridge 发布包，不需要预先剥离消息信封：

```json
{
  "op": "publish",
  "topic": "/fleet_states",
  "msg": {"name": "delivery", "robots": []}
}
```

## 鉴权

生产部署设置 `RMF_INGEST_TOKEN` 后，推送端必须发送：

```text
Authorization: Bearer <token>
```

密钥只通过环境变量提供，不写入仓库。
