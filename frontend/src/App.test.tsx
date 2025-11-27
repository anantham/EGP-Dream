import { render, screen, fireEvent } from '@testing-library/react'
import App from './App'

describe('Settings overlay', () => {
  it('opens the dedicated settings page with version and controls', async () => {
    render(<App />)

    // Settings should be hidden initially
    expect(screen.queryByText(/Settings/i)).toBeNull()

    // Open settings
    const settingsButton = screen.getByTestId('settings-button')
    fireEvent.click(settingsButton)

    const overlay = await screen.findByTestId('settings-overlay')
    expect(overlay).toBeInTheDocument()
    expect(overlay).toBeVisible()
    expect(await screen.findByText(/Settings/i)).toBeInTheDocument()
    expect(screen.getByText(/Version v0.05/i)).toBeInTheDocument()
    // Key inputs visible
    expect(screen.getByPlaceholderText(/Gemini API Key/i)).toBeInTheDocument()
    // History/gallery area visible
    expect(screen.getByText(/History/i)).toBeInTheDocument()
  })
})
