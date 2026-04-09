/**
 * Sample TSX file used as a parser test fixture.
 *
 * Covers: React default import, named imports, type import,
 *         external packages, and local component imports.
 */
import React, { useState, useEffect } from 'react';
import type { FC, ReactNode } from 'react';
import { BrowserRouter } from 'react-router-dom';
import * as _ from 'lodash';

import { Header } from './Header';
import { Footer } from './Footer';
import { useTheme } from '../hooks/useTheme';

interface Props {
    children: ReactNode;
}

const App: FC<Props> = ({ children }) => {
    const [count, setCount] = useState(0);
    const theme = useTheme();

    useEffect(() => {
        document.title = `Count: ${count}`;
    }, [count]);

    return (
        <BrowserRouter>
            <Header />
            <main>{children}</main>
            <Footer />
        </BrowserRouter>
    );
};

export default App;
