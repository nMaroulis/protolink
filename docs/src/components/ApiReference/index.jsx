import React, {useState} from 'react';
import styles from './styles.module.css';

const OPENING_DELIMITERS = new Set(['(', '[', '{']);
const CLOSING_DELIMITERS = new Map([
  [')', '('],
  [']', '['],
  ['}', '{'],
]);

function findDefaultEnd(signature, start, parameterStack) {
  const stack = [...parameterStack];
  let quote = null;
  let escaped = false;

  for (let index = start; index < signature.length; index += 1) {
    const character = signature[index];

    if (quote) {
      if (escaped) {
        escaped = false;
      } else if (character === '\\') {
        escaped = true;
      } else if (character === quote) {
        quote = null;
      }
      continue;
    }

    if (character === '"' || character === "'") {
      quote = character;
      continue;
    }

    if (OPENING_DELIMITERS.has(character)) {
      stack.push(character);
      continue;
    }

    if (CLOSING_DELIMITERS.has(character)) {
      if (
        character === ')' &&
        stack.length === 1 &&
        stack[0] === '('
      ) {
        return index;
      }

      if (stack.at(-1) === CLOSING_DELIMITERS.get(character)) {
        stack.pop();
      }
      continue;
    }

    if (
      character === ',' &&
      stack.length === 1 &&
      stack[0] === '('
    ) {
      return index;
    }
  }

  return signature.length;
}

function renderSignature(signature) {
  const fragments = [];
  const stack = [];
  let textStart = 0;
  let quote = null;
  let escaped = false;
  let fragmentIndex = 0;

  for (let index = 0; index < signature.length; index += 1) {
    const character = signature[index];

    if (quote) {
      if (escaped) {
        escaped = false;
      } else if (character === '\\') {
        escaped = true;
      } else if (character === quote) {
        quote = null;
      }
      continue;
    }

    if (character === '"' || character === "'") {
      quote = character;
      continue;
    }

    if (OPENING_DELIMITERS.has(character)) {
      stack.push(character);
      continue;
    }

    if (CLOSING_DELIMITERS.has(character)) {
      if (stack.at(-1) === CLOSING_DELIMITERS.get(character)) {
        stack.pop();
      }
      continue;
    }

    const previous = signature[index - 1];
    const next = signature[index + 1];
    const isParameterAssignment =
      character === '=' &&
      stack.length === 1 &&
      stack[0] === '(' &&
      previous !== '=' &&
      previous !== '!' &&
      previous !== '<' &&
      previous !== '>' &&
      previous !== ':' &&
      next !== '=';

    if (!isParameterAssignment) {
      continue;
    }

    let valueStart = index + 1;
    while (
      valueStart < signature.length &&
      (signature[valueStart] === ' ' || signature[valueStart] === '\t')
    ) {
      valueStart += 1;
    }

    const valueEnd = findDefaultEnd(signature, valueStart, stack);
    if (valueStart === valueEnd) {
      continue;
    }

    if (textStart < valueStart) {
      fragments.push(
        <React.Fragment key={`signature-text-${fragmentIndex}`}>
          {signature.slice(textStart, valueStart)}
        </React.Fragment>,
      );
      fragmentIndex += 1;
    }

    fragments.push(
      <span
        className={styles.signatureDefault}
        key={`signature-default-${fragmentIndex}`}
      >
        {signature.slice(valueStart, valueEnd)}
      </span>,
    );
    fragmentIndex += 1;
    textStart = valueEnd;
    index = valueEnd - 1;
  }

  if (textStart < signature.length) {
    fragments.push(
      <React.Fragment key={`signature-text-${fragmentIndex}`}>
        {signature.slice(textStart)}
      </React.Fragment>,
    );
  }

  return fragments;
}

export default function ApiReference({
  kind = 'callable',
  path,
  signature,
  source,
  children,
}) {
  const [copied, setCopied] = useState(false);

  const copySignature = async () => {
    if (!signature || typeof navigator === 'undefined' || !navigator.clipboard) {
      return;
    }

    await navigator.clipboard.writeText(signature);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };

  return (
    <article className={styles.reference}>
      <div className={styles.signatureCard}>
        <div className={styles.meta}>
          <div className={styles.identity}>
            <span className={styles.kind}>{kind}</span>
            {path ? <code className={styles.path}>{path}</code> : null}
          </div>
          {source ? (
            <a className={styles.source} href={source} target="_blank" rel="noreferrer">
              source
              <span aria-hidden="true">↗</span>
            </a>
          ) : null}
        </div>

        <div className={styles.signature}>
          <pre aria-label={`${path || kind} signature`}>
            <code>{renderSignature(signature)}</code>
          </pre>
          <button
            className={styles.copy}
            type="button"
            onClick={copySignature}
            aria-label={`Copy ${path || kind} signature`}
          >
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
      </div>

      <div className={styles.body}>{children}</div>
    </article>
  );
}

export function ApiSection({title, children}) {
  return (
    <section className={styles.section}>
      <h4 className={styles.sectionTitle}>
        <span>{title}</span>
      </h4>
      {children}
    </section>
  );
}

export function ApiFields({children, ariaLabel}) {
  return (
    <dl className={styles.fields} aria-label={ariaLabel}>
      {children}
    </dl>
  );
}

export function ApiField({
  name,
  type,
  defaultValue,
  required = false,
  children,
}) {
  return (
    <div className={styles.field}>
      <dt className={styles.term}>
        <code className={styles.name}>{name}</code>
        {type ? <span className={styles.classifier}>{type}</span> : null}
        {required ? <span className={styles.required}>required</span> : null}
        {defaultValue !== undefined ? (
          <span className={styles.defaultValue}>default: {defaultValue}</span>
        ) : null}
      </dt>
      <dd className={styles.description}>{children}</dd>
    </div>
  );
}

export function ApiCallout({label = 'Note', children}) {
  return (
    <div className={styles.callout}>
      <strong>{label}</strong>
      <div>{children}</div>
    </div>
  );
}
