/**
 * @vitest-environment jsdom
 *
 * Unit tests for the ChatInput component.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ChatInput } from './ChatInput';

describe('ChatInput', () => {
  const defaultProps = {
    onSend: vi.fn(),
    onStop: vi.fn(),
    onUpload: vi.fn().mockResolvedValue(undefined),
    isLoading: false,
    uploadedFiles: [],
    onRemoveUpload: vi.fn(),
    isUploading: false,
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the input textarea', () => {
    render(<ChatInput {...defaultProps} />);
    expect(screen.getByPlaceholderText(/ask/i)).toBeDefined();
  });

  it('calls onSend when Enter is pressed with text', async () => {
    render(<ChatInput {...defaultProps} />);
    const textarea = screen.getByRole('textbox');
    await userEvent.type(textarea, 'What is the onboarding process?');
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });
    expect(defaultProps.onSend).toHaveBeenCalledWith('What is the onboarding process?');
  });

  it('does not call onSend for empty input', async () => {
    render(<ChatInput {...defaultProps} />);
    const textarea = screen.getByRole('textbox');
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });
    expect(defaultProps.onSend).not.toHaveBeenCalled();
  });

  it('does not call onSend when loading', async () => {
    render(<ChatInput {...defaultProps} isLoading={true} />);
    const textarea = screen.getByRole('textbox');
    await userEvent.type(textarea, 'test');
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });
    expect(defaultProps.onSend).not.toHaveBeenCalled();
  });

  it('allows Shift+Enter for newlines without sending', async () => {
    render(<ChatInput {...defaultProps} />);
    const textarea = screen.getByRole('textbox');
    await userEvent.type(textarea, 'line 1');
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true });
    expect(defaultProps.onSend).not.toHaveBeenCalled();
  });
});
