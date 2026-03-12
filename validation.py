"""Input validation for Telegram Recipe Bot."""


def validate_product_list(text: str) -> tuple[bool, str]:
    """
    Validate user product list input.
    
    Args:
        text: User input text
        
    Returns:
        tuple: (is_valid, error_key)
            - (True, "") if input is valid
            - (False, "empty_list") if input is empty or whitespace only
            - (False, "too_long") if input exceeds 300 characters
    """
    # Check if empty or whitespace only
    if not text or text.isspace():
        return False, "empty_list"
    
    # Check length
    if len(text) > 300:
        return False, "too_long"
    
    return True, ""
