import { useState } from "react";

function CopyButton({ text, label = "Copiar" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  }

  return (
    <button className="copyButton" type="button" onClick={copy}>
      {copied ? "Copiado" : label}
    </button>
  );
}

export default function MessageContent({ content }: { content: string }) {
  const blocks: Array<
    | { kind: "text"; value: string }
    | { kind: "code"; value: string; language: string }
  > = [];

  const pattern = /```([a-zA-Z0-9_+-]*)\n([\s\S]*?)```/g;
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(content)) !== null) {
    if (match.index > cursor) {
      blocks.push({ kind: "text", value: content.slice(cursor, match.index) });
    }
    blocks.push({
      kind: "code",
      language: match[1] || "text",
      value: match[2].replace(/\n$/, "")
    });
    cursor = pattern.lastIndex;
  }

  if (cursor < content.length) {
    blocks.push({ kind: "text", value: content.slice(cursor) });
  }

  if (blocks.length === 0) {
    blocks.push({ kind: "text", value: content });
  }

  return (
    <div className="messageContent">
      {blocks.map((block, index) =>
        block.kind === "code" ? (
          <div className="codeBlock" key={index}>
            <div className="codeHeader">
              <span>{block.language}</span>
              <CopyButton text={block.value} />
            </div>
            <pre>
              <code>{block.value}</code>
            </pre>
          </div>
        ) : (
          <div className="textBlock" key={index}>
            {block.value.split("\n").map((line, lineIndex) => (
              <span key={lineIndex}>
                {line}
                {lineIndex < block.value.split("\n").length - 1 && <br />}
              </span>
            ))}
          </div>
        )
      )}
    </div>
  );
}

export function MessageActions({ content }: { content: string }) {
  return (
    <div className="messageActions">
      <CopyButton text={content} label="Copiar resposta" />
    </div>
  );
}
