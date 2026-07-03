const lightCodeTheme = require('prism-react-renderer').themes.github;
const darkCodeTheme = require('prism-react-renderer').themes.dracula;

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'ProtoLink',
  tagline: 'A2A-native runtime substrate for professional agent systems.',
  favicon: 'img/logo_sm.png',

  url: 'https://nmaroulis.github.io',
  baseUrl: '/protolink/',
  organizationName: 'nMaroulis',
  projectName: 'protolink',

  onBrokenLinks: 'throw',
  trailingSlash: true,

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  markdown: {
    mermaid: true,
    hooks: {
      onBrokenMarkdownLinks: 'throw',
    },
  },

  themes: ['@docusaurus/theme-mermaid'],

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          path: 'content',
          sidebarPath: require.resolve('./sidebars.js'),
          routeBasePath: 'docs',
          editUrl: 'https://github.com/nMaroulis/protolink/tree/main/docs/content/',
          showLastUpdateAuthor: false,
          showLastUpdateTime: false,
        },
        blog: false,
        theme: {
          customCss: require.resolve('./src/css/custom.css'),
        },
      }),
    ],
  ],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      image: 'img/banner.png',
      metadata: [
        {
          name: 'keywords',
          content:
            'ProtoLink, agent-to-agent, A2A, Python agents, LLM tools, runtime control, multi-agent systems',
        },
      ],
      colorMode: {
        defaultMode: 'light',
        disableSwitch: false,
        respectPrefersColorScheme: true,
      },
      navbar: {
        title: 'ProtoLink',
        logo: {
          alt: 'ProtoLink logo',
          src: 'img/logo_sm.png',
        },
        hideOnScroll: true,
        items: [
          {
            type: 'docSidebar',
            sidebarId: 'docsSidebar',
            position: 'left',
            label: 'Docs',
          },
          {
            to: '/docs/runtime',
            label: 'Runtime',
            position: 'left',
          },
          {
            to: '/docs/agent',
            label: 'API',
            position: 'left',
          },
          {
            to: '/docs/examples',
            label: 'Examples',
            position: 'left',
          },
          {
            to: '/docs/changelog',
            label: 'Changelog',
            position: 'left',
          },
          {
            href: 'https://github.com/nMaroulis/protolink',
            label: 'GitHub',
            position: 'right',
          },
          {
            href: 'https://pypi.org/project/protolink/',
            label: 'PyPI',
            position: 'right',
          },
        ],
      },
      footer: {
        style: 'light',
        links: [
          {
            title: 'Start',
            items: [
              {
                label: 'Getting Started',
                to: '/docs/getting-started',
              },
              {
                label: 'CLI',
                to: '/docs/cli',
              },
              {
                label: 'Developer Tools',
                to: '/docs/devtools',
              },
            ],
          },
          {
            title: 'Build',
            items: [
              {
                label: 'Agents',
                to: '/docs/agent',
              },
              {
                label: 'Runtime',
                to: '/docs/runtime',
              },
              {
                label: 'Transports',
                to: '/docs/transport',
              },
            ],
          },
          {
            title: 'Project',
            items: [
              {
                label: 'GitHub',
                href: 'https://github.com/nMaroulis/protolink',
              },
              {
                label: 'PyPI',
                href: 'https://pypi.org/project/protolink/',
              },
              {
                label: 'Changelog',
                to: '/docs/changelog',
              },
            ],
          },
        ],
        copyright:
          'Copyright © 2025 Nikolaos Maroulis. MIT licensed. Built with Docusaurus.',
      },
      prism: {
        theme: lightCodeTheme,
        darkTheme: darkCodeTheme,
        additionalLanguages: ['python', 'bash', 'json', 'yaml', 'toml'],
      },
      mermaid: {
        theme: {light: 'neutral', dark: 'forest'},
        options: {
          maxTextSize: 90000,
        },
      },
      tableOfContents: {
        minHeadingLevel: 2,
        maxHeadingLevel: 4,
      },
    }),
};

module.exports = config;
