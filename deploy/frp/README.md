# frp inference API bridge

Use this when Cloudflare Tunnel is unavailable and SSH port forwarding is not stable enough.

Target topology:

```text
SaaS worker/API
  -> http://<FRP_SERVER_HOST>:18100
     -> frps on public VPS
        -> frpc on GPU server
           -> 127.0.0.1:8100 Inference API
```

Do not expose ComfyUI `8188` for the normal Wan2.1 path. Keep the public bridge surface to the Inference API on `8100`.

## 1. Public VPS: frps

Copy `frps.toml.example` to the VPS as `frps.toml`, replace `CHANGE_ME_STRONG_TOKEN`, then run:

```bash
./frps -c ./frps.toml
```

Open only these inbound ports on the VPS firewall:

- `7000/tcp` for frpc control connection
- `18100/tcp` for the bridged Inference API

## 2. GPU server: frpc

Copy `frpc.toml.example` to the GPU server as `frpc.toml`, replace:

- `FRP_SERVER_HOST` with the VPS IP or domain
- `CHANGE_ME_STRONG_TOKEN` with the same token used by frps

Then run:

```bash
./frpc -c ./frpc.toml
```

## 3. SaaS local config

After the bridge is healthy:

```env
INFERENCE_API_BASE_URL=http://<FRP_SERVER_HOST>:18100
```

Restart the SaaS API and `worker-video` containers after changing `.env`.

## 4. Verification

From the SaaS host:

```bash
curl http://<FRP_SERVER_HOST>:18100/v1/health
```

This only proves the bridge is reachable. The real acceptance test is still:

```text
Wan2.1 inference succeeds -> output video URL downloads -> selected_video enters final edit -> final MP4 exports.
```
