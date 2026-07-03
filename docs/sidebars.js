/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  docsSidebar: [
    {
      type: 'category',
      label: 'Overview',
      collapsed: false,
      items: [
        'index',
        'concept',
        'whitepaper',
        'getting-started',
        'cli',
        'devtools',
      ],
    },
    {
      type: 'category',
      label: 'API Reference',
      collapsed: false,
      items: [
        'agent',
        'client',
        'flows',
        'llm',
        'logging',
        'models',
        'registry',
        'runtime',
        'server',
        'state',
        'storage',
        'telemetry',
        'tool',
        'transport',
        'authentication',
        'types',
      ],
    },
    {
      type: 'category',
      label: 'Examples',
      collapsed: false,
      items: [
        'examples',
        'llm_examples',
        'ticket_booking_example',
        'code_assistant_example',
      ],
    },
    {
      type: 'category',
      label: 'Project',
      collapsed: false,
      items: ['development', 'changelog', 'relevant'],
    },
  ],
};

module.exports = sidebars;
