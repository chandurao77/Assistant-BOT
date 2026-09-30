/**
 * @vitest-environment jsdom
 *
 * Unit tests for the SourceCitations component.
 */
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { SourceCitations } from './SourceCitations';
import type { SourceDocument } from '@/types';

const mockSources: SourceDocument[] = [
  {
    page_id: 'p1',
    title: 'Getting Started',
    url: 'https://wiki.example.com/getting-started',
    space_key: 'ENG',
    space_name: 'Engineering',
    excerpt: 'This guide helps you get started with the platform.',
    score: 0.95,
  },
  {
    page_id: 'p2',
    title: 'Onboarding',
    url: 'https://wiki.example.com/onboarding',
    space_key: 'HR',
    space_name: 'Human Resources',
    excerpt: 'New employee onboarding process and checklist.',
    score: 0.82,
  },
];

const multiSourceMocks: SourceDocument[] = [
  {
    page_id: 'jira_ENG-42',
    title: '[ENG-42] Fix login bug',
    url: 'https://myorg.atlassian.net/browse/ENG-42',
    space_key: '__JIRA__',
    space_name: 'Jira: ENG',
    excerpt: 'Bug fix for SSO redirect issue.',
    score: 0.88,
  },
  {
    page_id: 'github_org_repo_README.md',
    title: 'org/repo: README.md',
    url: 'https://github.com/org/repo/blob/HEAD/README.md',
    space_key: '__GITHUB__',
    space_name: 'GitHub: org/repo',
    excerpt: 'Project documentation.',
    score: 0.75,
  },
  ...mockSources.slice(0, 1),
];

describe('SourceCitations', () => {
  it('renders source count in the toggle button', () => {
    render(<SourceCitations sources={mockSources} />);
    expect(screen.getByText(/Sources \(2\)/)).toBeDefined();
  });

  it('does not render when sources is empty', () => {
    const { container } = render(<SourceCitations sources={[]} />);
    expect(container.textContent).toBe('');
  });

  it('shows source details when expanded', () => {
    render(<SourceCitations sources={mockSources} />);
    fireEvent.click(screen.getByText(/Sources \(2\)/));

    expect(screen.getByText(/Getting Started/)).toBeDefined();
    expect(screen.getByText(/Onboarding/)).toBeDefined();
    expect(screen.getByText(/ENG/)).toBeDefined();
    expect(screen.getByText(/HR/)).toBeDefined();
  });

  it('renders source links with target _blank', () => {
    render(<SourceCitations sources={mockSources} />);
    fireEvent.click(screen.getByText(/Sources \(2\)/));

    const links = screen.getAllByRole('link');
    links.forEach((link) => {
      expect(link.getAttribute('target')).toBe('_blank');
    });
  });

  it('displays score as percentage', () => {
    render(<SourceCitations sources={mockSources} />);
    fireEvent.click(screen.getByText(/Sources \(2\)/));

    // 0.95 → 95%, 0.82 → 82%
    expect(screen.getByText(/95%/)).toBeDefined();
    expect(screen.getByText(/82%/)).toBeDefined();
  });

  it('shows source type badges for Jira, GitHub, and Confluence', () => {
    render(<SourceCitations sources={multiSourceMocks} />);
    fireEvent.click(screen.getByText(/Sources \(3\)/));

    expect(screen.getByText('Jira')).toBeDefined();
    expect(screen.getByText('GitHub')).toBeDefined();
    expect(screen.getByText('Confluence')).toBeDefined();
  });

  it('shows space_name instead of space_key for internal sources', () => {
    render(<SourceCitations sources={multiSourceMocks} />);
    fireEvent.click(screen.getByText(/Sources \(3\)/));

    // Jira and GitHub should show space_name, not __JIRA__ / __GITHUB__
    expect(screen.getByText('Jira: ENG')).toBeDefined();
    expect(screen.getByText('GitHub: org/repo')).toBeDefined();
  });

  it('shows last updated date when available', () => {
    const yesterday = new Date(Date.now() - 86400000).toISOString();
    const sourcesWithDate: SourceDocument[] = [
      {
        ...mockSources[0],
        last_modified: yesterday,
      },
    ];
    render(<SourceCitations sources={sourcesWithDate} />);
    fireEvent.click(screen.getByText(/Sources \(1\)/));
    expect(screen.getByText(/Updated yesterday/)).toBeDefined();
  });

  it('does not show last updated when last_modified is null', () => {
    render(<SourceCitations sources={mockSources} />);
    fireEvent.click(screen.getByText(/Sources \(2\)/));
    // Should not crash or show "Updated" text
    expect(screen.queryByText(/Updated/)).toBeNull();
  });
});
