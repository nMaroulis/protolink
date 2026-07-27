import React from 'react';
import styles from './styles.module.css';

export default function ExampleArticle({
  source,
  title,
  description,
  href,
  image,
  imageAlt,
}) {
  return (
    <aside className={styles.exampleArticle} aria-label={`Related article: ${title}`}>
      <header className={styles.intro}>
        <h2>✨ Want to explore the full story?</h2>
        <p>
          I shared a deeper dive into the architecture, experiments, and lessons
          learned behind this project in my original article on <strong>{source}</strong>:
        </p>
        <span className={styles.arrow} aria-hidden="true">
          ↓
        </span>
      </header>

      <article className={styles.card}>
        <img
          className={styles.image}
          src={image}
          alt={imageAlt}
          loading="lazy"
        />

        <div className={styles.content}>
          <p className={styles.source}>Posted on {source}</p>
          <h3 className={styles.title}>{title}</h3>
          <p className={styles.description}>{description}</p>

          <footer className={styles.footer}>
            <span>📖 Reference article</span>
            <a href={href} target="_blank" rel="noopener noreferrer">
              Read article <span aria-hidden="true">→</span>
            </a>
          </footer>
        </div>
      </article>
    </aside>
  );
}
