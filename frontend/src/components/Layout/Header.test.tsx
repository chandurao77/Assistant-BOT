/**
 * @vitest-environment jsdom
 *
 * Unit tests for the Header component.
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Header } from './Header';

describe('Header', () => {
  it('renders the Assistant Bot title', () => {
    render(<Header theme="light" onToggleTheme={vi.fn()} />);
    expect(screen.getByText('Assistant Bot')).toBeDefined();
    expect(screen.getByText('Your documentation assistant')).toBeDefined();
  });

  it('calls onToggleTheme when theme button is clicked', () => {
    const toggle = vi.fn();
    render(<Header theme="light" onToggleTheme={toggle} />);
    const btn = screen.getByTitle(/switch to dark mode/i);
    fireEvent.click(btn);
    expect(toggle).toHaveBeenCalledOnce();
  });

  it('shows user info when user is provided', () => {
    render(
      <Header
        theme="dark"
        onToggleTheme={vi.fn()}
        user={{ name: 'Test User', email: 'test@example.com' }}
        onLogout={vi.fn()}
      />
    );
    expect(screen.getByText(/test user/i)).toBeDefined();
  });

  it('shows Analytics button when user and onToggleDashboard are provided', () => {
    render(
      <Header
        theme="light"
        onToggleTheme={vi.fn()}
        user={{ name: 'Admin', email: 'admin@test.com' }}
        onLogout={vi.fn()}
        showDashboard={false}
        onToggleDashboard={vi.fn()}
      />
    );
    expect(screen.getByText('Analytics')).toBeDefined();
  });
});
