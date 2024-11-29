import logging

def get_logger(logger_name: str, level = logging.INFO) -> logging.Logger:
    """Returns named Python logger with the logging level set to arg level."""
    logger = logging.getLogger(logger_name) # Used to log messages with different levels of importance
    logger.setLevel(level) # Lower than this level messages are not shown
    
    if logger.hasHandlers():
        # This logger was created already, don't add a new handler to it
        return logger
    
    # Define handler and its formatter for the new logger
    log_handler = logging.StreamHandler() 
    log_handler.setLevel(level)
    log_formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s: %(message)s", 
                                      datefmt = "%H:%M:%S")
    log_handler.setFormatter(log_formatter)
    logger.addHandler(log_handler)

    return logger