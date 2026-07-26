# Image generation

How to generate an image with Codex and get it into the chat. `Read` this before generating an image, and check the `Provider:` line in your injected `<agent_experience>` block first. Möbius does not expose a built-in image-generation path for other providers.

For simple icons or logos, consider an SVG instead — it's crisp, themeable, and reviewable in diffs.

---

## Codex (`$imagegen`)

Codex includes a built-in image generator covered by the plan, with no separate API key needed.

```bash
$imagegen "a serene mountain landscape"
```

The PNG saves under `/data/cli-auth/codex/generated_images/...` and is not
automatically visible in Möbius chat. Publish the exact returned path:

```bash
python "$SCRIPTS_DIR/publish_chat_image.py" "<exact path returned by imagegen>" \
  --alt "short description"
```

Paste the returned `embed` value into the reply before describing the image.
The helper writes to the resolved current chat and deliberately requires the
exact generated path; never rediscover an output by modification time, which
can select another run's image.
