import React from 'react';
import styles from './styles.module.css';

export default function ApiSurface({
  eyebrow = 'API surface',
  title,
  path,
  description,
  pills = [],
  cards = [],
  note,
  ariaLabel,
}) {
  return (
    <section className={styles.surface} aria-label={ariaLabel ?? `${title} API surface`}>
      <div className={styles.header}>
        <div className={styles.copy}>
          <span className={styles.eyebrow}>{eyebrow}</span>
          <strong className={styles.title}>{title}</strong>
          {description ? <p>{description}</p> : null}
        </div>
        {path ? <code className={styles.path}>{path}</code> : null}
      </div>

      {pills.length > 0 ? (
        <div className={styles.pills} aria-label={`${title} highlights`}>
          {pills.map((pill, index) => (
            <span key={`${pill}-${index}`}>{pill}</span>
          ))}
        </div>
      ) : null}

      {cards.length > 0 ? (
        <div className={styles.grid}>
          {cards.map((card, index) => (
            <div className={styles.card} key={`${card.title}-${index}`}>
              <strong>{card.title}</strong>
              <span>{card.text}</span>
              {card.code ? <code>{card.code}</code> : null}
            </div>
          ))}
        </div>
      ) : null}

      {note ? <p className={styles.note}>{note}</p> : null}
    </section>
  );
}
